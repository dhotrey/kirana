from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import logfire
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger

from chat.gateway import build_chat_model, model_routes_via_gemini
from chat.schemas import (
    ChatMessage,
    ChatMessageStats,
    Conversation,
)
from ingestion.embeddings import Embedder
from ingestion.prompts import load_prompt
from ingestion.rate_limit import GeminiRateLimiter
from tools import build_finance_tools, build_vectorize_tools
from utils.db.d1 import D1Database
from utils.observability import logfire_enabled
from utils.types import Config

TITLE_MAX_CHARS = 48
SYSTEM_PROMPT_NAME = "system_prompt"
RATE_LIMIT_RETRY_DELAYS_SECONDS = (15, 30, 45, 60)
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_IMAGE_QUERY = "Did I buy this item? Search the uploaded image against my receipts and show the evidence."


@dataclass(frozen=True)
class RateLimitRetryEvent:
    attempt: int
    delay_seconds: int
    max_retries: int
    call_name: str
    model_name: str
    model_identifier: str
    error: str


RateLimitRetryCallback = Callable[[RateLimitRetryEvent], Awaitable[None]]


def _utc_now_sql() -> str:
    return "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _title_from_message(message: str) -> str:
    title = " ".join(message.split())
    if not title:
        return "New conversation"
    if len(title) <= TITLE_MAX_CHARS:
        return title
    return title[: TITLE_MAX_CHARS - 1].rstrip() + "..."


def _message_to_schema(
    message: BaseMessage,
    *,
    total_tat_seconds: float | None = None,
    tool_names: list[str] | None = None,
    rate_limit_retries: int = 0,
) -> ChatMessage | None:
    if isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        return None

    content = message.content
    if isinstance(content, str):
        text = content
    else:
        text = str(content)
    stats = None
    if isinstance(message, AIMessage):
        token_usage = _extract_token_usage(message)
        if total_tat_seconds is not None:
            tools = tool_names or []
            stats = ChatMessageStats(
                total_tat_seconds=round(total_tat_seconds, 3),
                input_tokens=token_usage["input_tokens"],
                output_tokens=token_usage["output_tokens"],
                total_tokens=token_usage["total_tokens"],
                tool_calls=len(tools),
                tools=tools,
                rate_limit_retries=rate_limit_retries,
            )
    return ChatMessage(role=role, content=text, stats=stats)


def _extract_token_usage(message: AIMessage) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}

    input_tokens = (
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
        or 0
    )
    output_tokens = (
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
        or 0
    )
    total_tokens = (
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or int(input_tokens) + int(output_tokens)
    )
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        code = str(body.get("code") or "").lower()
        error_type = str(body.get("type") or "").lower()
        raw_status_code = body.get("raw_status_code")
        if raw_status_code == 429 or code == "1300" or error_type == "rate_limited":
            return True

    text = str(exc).lower()
    return "429" in text and ("rate limit exceeded" in text or "rate_limited" in text)


async def _invoke_model_with_rate_limit_retry(
    model: Any,
    messages: Sequence[BaseMessage],
    *,
    model_name: str,
    model_identifier: str,
    call_name: str,
    retry_callback: RateLimitRetryCallback | None,
) -> AIMessage:
    for retries_used, delay_seconds in enumerate(
        (*RATE_LIMIT_RETRY_DELAYS_SECONDS, None)
    ):
        try:
            return await model.ainvoke(messages)
        except Exception as exc:
            if delay_seconds is None or not _is_rate_limit_error(exc):
                raise

            attempt = retries_used + 1
            error_text = str(exc)
            logger.warning(
                "llm rate limited call={} model={} retry={} delay_seconds={} error={!r}",
                call_name,
                model_name,
                attempt,
                delay_seconds,
                error_text,
            )
            if logfire_enabled():
                with logfire.span(
                    "llm_rate_limit_retry",
                    call_name=call_name,
                    model_name=model_name,
                    model_identifier=model_identifier,
                    retry_attempt=attempt,
                    retry_delay_seconds=delay_seconds,
                    max_retries=len(RATE_LIMIT_RETRY_DELAYS_SECONDS),
                    error=error_text,
                ):
                    logfire.info(
                        "llm rate limited; auto retrying",
                        call_name=call_name,
                        model_name=model_name,
                        model_identifier=model_identifier,
                        retry_attempt=attempt,
                        retry_delay_seconds=delay_seconds,
                        max_retries=len(RATE_LIMIT_RETRY_DELAYS_SECONDS),
                        error=error_text,
                    )

            if retry_callback is not None:
                await retry_callback(
                    RateLimitRetryEvent(
                        attempt=attempt,
                        delay_seconds=delay_seconds,
                        max_retries=len(RATE_LIMIT_RETRY_DELAYS_SECONDS),
                        call_name=call_name,
                        model_name=model_name,
                        model_identifier=model_identifier,
                        error=error_text,
                    )
                )
            await asyncio.sleep(delay_seconds)

    raise RuntimeError("unreachable model retry state")


def _extract_tool_names_for_latest_turn(messages: Sequence[BaseMessage]) -> list[str]:
    latest_human_index = None
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            latest_human_index = index
    if latest_human_index is None:
        return []

    tool_names: list[str] = []
    pending_ai_tool_names: list[str] = []
    for message in messages[latest_human_index + 1 :]:
        if isinstance(message, AIMessage):
            recorded_tool_names = getattr(message, "additional_kwargs", {}).get(
                "kirana_tool_names", []
            )
            if isinstance(recorded_tool_names, list):
                tool_names.extend(
                    name for name in recorded_tool_names if isinstance(name, str)
                )

        if isinstance(message, ToolMessage):
            name = getattr(message, "name", None)
            if isinstance(name, str) and name:
                tool_names.append(name)
            elif pending_ai_tool_names:
                tool_names.append(pending_ai_tool_names.pop(0))
            else:
                tool_names.append("unknown_tool")
            continue

        if not isinstance(message, AIMessage):
            continue

        for tool_call in getattr(message, "tool_calls", []) or []:
            if isinstance(tool_call, dict):
                name = tool_call.get("name")
                if isinstance(name, str) and name:
                    pending_ai_tool_names.append(name)

        raw_tool_calls = getattr(message, "additional_kwargs", {}).get("tool_calls", [])
        for raw_tool_call in raw_tool_calls or []:
            if not isinstance(raw_tool_call, dict):
                continue
            function = raw_tool_call.get("function")
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str) and name:
                    pending_ai_tool_names.append(name)

    return tool_names


class ChatService:
    def __init__(
        self,
        *,
        cfg: Config,
        conn: aiosqlite.Connection,
        checkpointer: AsyncSqliteSaver,
        d1: D1Database,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.checkpointer = checkpointer
        self.d1 = d1
        self.rate_limiter = GeminiRateLimiter(cfg.ingestion.gemini_min_interval_seconds)
        self._models: dict[str, Any] = {}
        self._embedding_cache: dict[str, list[float]] = {}
        self._image_embedder: Embedder | None = None
        self._tools: list[Any] = [
            *build_finance_tools(d1),
            *build_vectorize_tools(cfg, self._embedding_cache),
        ]
        self._tool_by_name = {tool.name: tool for tool in self._tools}
        self.graph = self._build_graph()

    async def setup(self) -> None:
        await self.checkpointer.setup()
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        await self._ensure_conversations_is_active_column()
        await self.conn.commit()

    def model_options(self) -> list[dict[str, str]]:
        return [
            {"name": name, "identifier": self.cfg.kirana.model_identifiers[name]}
            for name in self.cfg.kirana.available_models
        ]

    async def create_conversation(
        self, title: str = "New conversation"
    ) -> Conversation:
        thread_id = str(uuid.uuid4())
        await self.conn.execute(
            f"""
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, {_utc_now_sql()}, {_utc_now_sql()})
            """,
            (thread_id, title),
        )
        await self.conn.commit()
        conversation = await self.get_conversation(thread_id)
        if conversation is None:
            raise RuntimeError("created conversation could not be loaded")
        return conversation

    async def list_conversations(self) -> list[Conversation]:
        rows = await self.conn.execute_fetchall(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE is_active = 1
            ORDER BY updated_at DESC
            """
        )
        return [self._conversation_from_row(row) for row in rows]

    async def get_conversation(self, thread_id: str) -> Conversation | None:
        rows = list(
            await self.conn.execute_fetchall(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = ? AND is_active = 1
                """,
                (thread_id,),
            )
        )
        if not rows:
            return None
        return self._conversation_from_row(rows[0])

    async def update_conversation_title(
        self, thread_id: str, title: str
    ) -> Conversation | None:
        normalized_title = " ".join(title.split())
        if not normalized_title:
            raise ValueError("conversation title cannot be empty")
        await self.conn.execute(
            f"""
            UPDATE conversations
            SET title = ?, updated_at = {_utc_now_sql()}
            WHERE id = ? AND is_active = 1
            """,
            (normalized_title, thread_id),
        )
        await self.conn.commit()
        return await self.get_conversation(thread_id)

    async def delete_conversation(self, thread_id: str) -> bool:
        cursor = await self.conn.execute(
            f"""
            UPDATE conversations
            SET is_active = 0, updated_at = {_utc_now_sql()}
            WHERE id = ? AND is_active = 1
            """,
            (thread_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def messages(self, thread_id: str) -> list[ChatMessage]:
        state = await self.graph.aget_state(self._thread_config(thread_id))
        raw_messages: Sequence[BaseMessage] = state.values.get("messages", [])
        messages = [_message_to_schema(message) for message in raw_messages]
        return [message for message in messages if message is not None]

    async def chat_stream(
        self,
        *,
        message: str,
        model_name: str,
        thread_id: str | None,
        system_prompt: str | None = None,
        tools_enabled: bool = True,
        image_bytes: bytes | None = None,
        image_filename: str | None = None,
        image_content_type: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        started_at = time.perf_counter()
        self._validate_model(model_name)
        effective_message = self._message_with_uploaded_image_context(
            message=message,
            image_bytes=image_bytes,
            image_filename=image_filename,
            image_content_type=image_content_type,
        )
        conversation = await self._ensure_conversation(
            thread_id, message or DEFAULT_IMAGE_QUERY
        )
        model_identifier = self.cfg.kirana.model_identifiers[model_name]

        yield {
            "type": "start",
            "thread_id": conversation.id,
            "conversation": conversation.model_dump(),
        }

        span = nullcontext()
        if logfire_enabled():
            span = logfire.span(
                "chat_request",
                thread_id=conversation.id,
                model_name=model_name,
                model_identifier=model_identifier,
                query=message,
                query_chars=len(message),
                has_image=image_bytes is not None,
                tools_enabled=tools_enabled,
                streaming=True,
            )

        with span as chat_span:
            logger.info(
                "chat stream request thread={} model={} tools_enabled={} chars={} query={!r}",
                conversation.id,
                model_name,
                tools_enabled,
                len(message),
                message,
            )
            if logfire_enabled():
                logfire.info(
                    "chat query",
                    thread_id=conversation.id,
                    model_name=model_name,
                    model_identifier=model_identifier,
                    query=message,
                    query_chars=len(message),
                    has_image=image_bytes is not None,
                    tools_enabled=tools_enabled,
                    streaming=True,
                )

            if model_routes_via_gemini(model_identifier):
                self.rate_limiter.wait(logger)

            retry_count = 0
            stream_events: asyncio.Queue[dict[str, Any] | Exception | None] = (
                asyncio.Queue()
            )

            async def emit_retry(event: RateLimitRetryEvent) -> None:
                nonlocal retry_count
                retry_count += 1
                await stream_events.put(
                    {
                        "type": "rate_limit_retry",
                        "retry_count": retry_count,
                        "retry_attempt": event.attempt,
                        "delay_seconds": event.delay_seconds,
                        "max_retries": event.max_retries,
                        "call": event.call_name,
                    }
                )

            async def produce_graph_events() -> None:
                try:
                    async for chunk, metadata in self.graph.astream(
                        {"messages": [HumanMessage(content=effective_message)]},
                        self._thread_config(
                            conversation.id,
                            model_name=model_name,
                            rate_limit_retry_callback=emit_retry,
                            system_prompt=system_prompt,
                            tools_enabled=tools_enabled,
                        ),
                        stream_mode="messages",
                    ):
                        if not isinstance(chunk, AIMessageChunk):
                            continue
                        node_name = (
                            metadata.get("langgraph_node")
                            if isinstance(metadata, dict)
                            else None
                        )
                        if node_name is not None and node_name != "agent":
                            continue
                        content = chunk.content
                        text = content if isinstance(content, str) else str(content)
                        if not text:
                            continue
                        await stream_events.put({"type": "delta", "content": text})
                except Exception as exc:
                    await stream_events.put(exc)
                finally:
                    await stream_events.put(None)

            producer = asyncio.create_task(produce_graph_events())
            try:
                while True:
                    event = await stream_events.get()
                    if event is None:
                        break
                    if isinstance(event, Exception):
                        raise event
                    yield event
            finally:
                if not producer.done():
                    producer.cancel()
                    try:
                        await producer
                    except asyncio.CancelledError:
                        pass

            state = await self.graph.aget_state(self._thread_config(conversation.id))
            raw_messages: Sequence[BaseMessage] = state.values.get("messages", [])
            response_message = next(
                (
                    candidate
                    for candidate in reversed(raw_messages)
                    if isinstance(candidate, AIMessage)
                ),
                None,
            )
            if response_message is None:
                raise RuntimeError(
                    "model response did not include an assistant message"
                )

            total_tat_seconds = time.perf_counter() - started_at
            tool_names = _extract_tool_names_for_latest_turn(raw_messages)
            response = _message_to_schema(
                response_message,
                total_tat_seconds=total_tat_seconds,
                tool_names=tool_names,
                rate_limit_retries=retry_count,
            )
            if response is None:
                raise RuntimeError("model response could not be serialized")

            token_usage = _extract_token_usage(response_message)
            if logfire_enabled():
                attributes = {
                    "response": response.content,
                    "response_chars": len(response.content),
                    "input_tokens": token_usage["input_tokens"],
                    "output_tokens": token_usage["output_tokens"],
                    "total_tokens": token_usage["total_tokens"],
                    "total_tat_seconds": total_tat_seconds,
                    "tool_calls": len(tool_names),
                    "tools": tool_names,
                    "rate_limit_retries": retry_count,
                }
                if chat_span is not None:
                    chat_span.set_attributes(attributes)
                logfire.info(
                    "chat response",
                    thread_id=conversation.id,
                    model_name=model_name,
                    model_identifier=model_identifier,
                    response=response.content,
                    response_chars=len(response.content),
                    input_tokens=token_usage["input_tokens"],
                    output_tokens=token_usage["output_tokens"],
                    total_tokens=token_usage["total_tokens"],
                    total_tat_seconds=total_tat_seconds,
                    tool_calls=len(tool_names),
                    tools=tool_names,
                    rate_limit_retries=retry_count,
                    streaming=True,
                )

        await self._touch_conversation(conversation.id)
        updated = await self.get_conversation(conversation.id)
        if updated is None:
            raise RuntimeError("conversation disappeared during chat request")
        logger.info(
            "chat stream response thread={} model={} chars={} total_tat_seconds={:.3f} input_tokens={} output_tokens={} total_tokens={} tool_calls={} rate_limit_retries={} response={!r}",
            conversation.id,
            model_name,
            len(response.content),
            response.stats.total_tat_seconds if response.stats is not None else 0.0,
            token_usage["input_tokens"],
            token_usage["output_tokens"],
            token_usage["total_tokens"],
            response.stats.tool_calls if response.stats is not None else 0,
            response.stats.rate_limit_retries if response.stats is not None else 0,
            response.content,
        )
        yield {
            "type": "end",
            "thread_id": conversation.id,
            "conversation": updated.model_dump(),
            "message": response.model_dump(exclude_none=True),
        }

    def _build_graph(self) -> Any:
        graph = StateGraph(MessagesState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent", tools_condition, {"tools": "tools", END: END}
        )
        graph.add_edge("tools", "agent")
        return graph.compile(checkpointer=self.checkpointer)

    async def _agent_node(
        self, state: MessagesState, config: RunnableConfig
    ) -> dict[str, Any]:
        configurable = config.get("configurable", {})
        model_name = configurable.get("model_name")
        if not isinstance(model_name, str):
            model_name = self.cfg.kirana.available_models[0]
        model_identifier = self.cfg.kirana.model_identifiers[model_name]
        retry_callback = configurable.get("rate_limit_retry_callback")
        if not callable(retry_callback):
            retry_callback = None
        tools_enabled = configurable.get("tools_enabled", True) is not False
        if model_routes_via_gemini(model_identifier) and self._tools and tools_enabled:
            return {
                "messages": [
                    await self._gemini_agent_response(
                        model_name,
                        state,
                        configurable=configurable,
                        retry_callback=retry_callback,
                    )
                ]
            }

        model = self._model(model_name)
        if self._tools and tools_enabled:
            model = model.bind_tools(self._tools)
        response = await _invoke_model_with_rate_limit_retry(
            model,
            [
                SystemMessage(content=self._system_prompt(configurable)),
                *state["messages"],
            ],
            model_name=model_name,
            model_identifier=model_identifier,
            call_name="agent",
            retry_callback=retry_callback,
        )
        return {"messages": [response]}

    async def _gemini_agent_response(
        self,
        model_name: str,
        state: MessagesState,
        *,
        configurable: dict[str, Any],
        retry_callback: RateLimitRetryCallback | None,
    ) -> AIMessage:
        base_messages = [
            SystemMessage(content=self._system_prompt(configurable)),
            *state["messages"],
        ]
        messages: list[BaseMessage] = list(base_messages)
        model = self._model(model_name)
        model_identifier = self.cfg.kirana.model_identifiers[model_name]
        tool_names: list[str] = []
        for tool_round in range(3):
            tool_request = await _invoke_model_with_rate_limit_retry(
                model.bind_tools(self._tools),
                messages,
                model_name=model_name,
                model_identifier=model_identifier,
                call_name=f"gemini_tool_request_{tool_round + 1}",
                retry_callback=retry_callback,
            )
            tool_calls = getattr(tool_request, "tool_calls", []) or []
            if not tool_calls:
                tool_request.additional_kwargs = {
                    **getattr(tool_request, "additional_kwargs", {}),
                    "kirana_tool_names": tool_names,
                }
                return tool_request

            messages.append(tool_request)
            tool_messages: list[ToolMessage] = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                name = tool_call.get("name")
                args = tool_call.get("args") or {}
                tool_call_id = str(
                    tool_call.get("id") or f"kirana_tool_{len(tool_names)}"
                )
                if not isinstance(name, str) or name not in self._tool_by_name:
                    continue
                if not isinstance(args, dict):
                    args = {"input": args}
                result = await self._tool_by_name[name].ainvoke(args)
                tool_names.append(name)
                tool_messages.append(
                    ToolMessage(
                        content=str(result), name=name, tool_call_id=tool_call_id
                    )
                )
            if not tool_messages:
                return tool_request
            messages.extend(tool_messages)

        synthesis_prompt = HumanMessage(
            content=(
                "Use these tool results to answer the user's latest question. "
                "Do not call another tool. Keep the answer concise and cite the "
                "date range, Vectorize receipt IDs, or SQL-derived basis when relevant."
            )
        )
        final_response = await _invoke_model_with_rate_limit_retry(
            model,
            [*messages, synthesis_prompt],
            model_name=model_name,
            model_identifier=model_identifier,
            call_name="gemini_synthesis",
            retry_callback=retry_callback,
        )
        final_response.additional_kwargs = {
            **getattr(final_response, "additional_kwargs", {}),
            "kirana_tool_names": tool_names,
        }
        return final_response

    def _system_prompt(self, configurable: dict[str, Any]) -> str:
        override = configurable.get("system_prompt")
        if isinstance(override, str) and override.strip():
            prompt = override.strip()
        else:
            prompt = load_prompt(
                self.cfg.ingestion.prompts_dir, SYSTEM_PROMPT_NAME
            ).strip()
        return f"Today's date is {datetime.now().date().isoformat()}.\n\n{prompt}"

    def _model(self, model_name: str) -> Any:
        self._validate_model(model_name)
        model = self._models.get(model_name)
        if model is None:
            identifier = self.cfg.kirana.model_identifiers[model_name]
            model = build_chat_model(identifier, self.cfg)
            self._models[model_name] = model
        return model

    def _get_image_embedder(self) -> Embedder:
        if self._image_embedder is None:
            self._image_embedder = Embedder(
                self.cfg.ingestion.embedding_model,
                self.cfg.ingestion.embedding_dim,
                logger.bind(image_id="-", tool="chat_uploaded_image"),
                image_max_dimension=self.cfg.ingestion.embedding_image_max_dimension,
                device=self.cfg.ingestion.embedding_device,
            )
        return self._image_embedder

    def _message_with_uploaded_image_context(
        self,
        *,
        message: str,
        image_bytes: bytes | None,
        image_filename: str | None,
        image_content_type: str | None,
    ) -> str:
        normalized_message = " ".join(message.split())
        if image_bytes is None:
            return normalized_message
        if not image_bytes:
            raise ValueError("image upload cannot be empty")
        if len(image_bytes) > MAX_IMAGE_UPLOAD_BYTES:
            raise ValueError("image upload must be 10 MB or smaller")
        content_type = image_content_type or ""
        if content_type and not content_type.lower().startswith("image/"):
            raise ValueError("upload must be an image")

        vector = self._get_image_embedder().embed_image(image_bytes)
        if len(vector) != self.cfg.cloudflare.vectorize_index_dimension:
            raise ValueError(
                "Image vector dimension does not match Vectorize index "
                f"dimension {self.cfg.cloudflare.vectorize_index_dimension}"
            )
        key_material = (
            f"{self.cfg.ingestion.embedding_model}:{self.cfg.ingestion.embedding_dim}:"
            f"{hashlib.sha256(image_bytes).hexdigest()}"
        )
        embedding_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:24]
        self._embedding_cache[embedding_key] = vector

        user_request = normalized_message or DEFAULT_IMAGE_QUERY
        filename = image_filename or "uploaded image"
        return (
            f"{user_request}\n\n"
            "Uploaded image context:\n"
            f"- filename: {filename}\n"
            f"- content_type: {content_type or 'unknown'}\n"
            f"- embedding_key: {embedding_key}\n"
            f"- embedding_model: {self.cfg.ingestion.embedding_model}\n"
            f"- similarity_threshold: {self.cfg.kirana.receipt_image_match_threshold}\n\n"
            "The assistant cannot see the raw uploaded image pixels in this chat "
            "turn. It only has this embedding key plus Vectorize and SQL tool "
            "results, so do not describe the image as if it was visually inspected. "
            "Describe what the retrieval results suggest instead.\n\n"
            "Use the uploaded image embedding as part of this request. Call "
            "`search_item_vectors` with the supplied `embedding_key`; then use "
            "`query_finance_db` to inspect receipts containing the matched item "
            "names. Only claim I bought the likely matched item when a relevant item "
            "Vectorize score is at or above the similarity threshold and SQL "
            "confirms the item appeared on a receipt. Cite the item names, scores, "
            "receipt IDs, stores, dates, and SQL-grounded item evidence."
        )

    def _validate_model(self, model_name: str) -> None:
        if model_name not in self.cfg.kirana.model_identifiers:
            raise ValueError(f"unknown model: {model_name}")

    async def _ensure_conversation(
        self, thread_id: str | None, first_message: str
    ) -> Conversation:
        if thread_id:
            conversation = await self.get_conversation(thread_id)
            if conversation is not None:
                return conversation
        return await self.create_conversation(_title_from_message(first_message))

    async def _touch_conversation(self, thread_id: str) -> None:
        await self.conn.execute(
            f"""
            UPDATE conversations
            SET updated_at = {_utc_now_sql()}
            WHERE id = ? AND is_active = 1
            """,
            (thread_id,),
        )
        await self.conn.commit()

    async def _ensure_conversations_is_active_column(self) -> None:
        rows = await self.conn.execute_fetchall("PRAGMA table_info(conversations)")
        if any(row["name"] == "is_active" for row in rows):
            return
        await self.conn.execute(
            "ALTER TABLE conversations ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
        )

    def _thread_config(
        self,
        thread_id: str,
        *,
        model_name: str | None = None,
        rate_limit_retry_callback: RateLimitRetryCallback | None = None,
        system_prompt: str | None = None,
        tools_enabled: bool = True,
    ) -> dict[str, Any]:
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if model_name is not None:
            configurable["model_name"] = model_name
        if rate_limit_retry_callback is not None:
            configurable["rate_limit_retry_callback"] = rate_limit_retry_callback
        if system_prompt is not None:
            configurable["system_prompt"] = system_prompt
        configurable["tools_enabled"] = tools_enabled
        return {"configurable": configurable}

    @staticmethod
    def _conversation_from_row(row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@asynccontextmanager
async def chat_service_lifespan(cfg: Config, d1: D1Database):
    db_path = Path(cfg.kirana.chat_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        checkpointer = AsyncSqliteSaver(conn)
        service = ChatService(
            cfg=cfg,
            conn=conn,
            checkpointer=checkpointer,
            d1=d1,
        )
        await service.setup()
        yield service

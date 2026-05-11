from __future__ import annotations

import os
import sqlite3
import time
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import logfire
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from loguru import logger

from chat.gateway import build_chat_model, model_routes_via_gemini
from chat.schemas import ChatMessage, ChatMessageStats, Conversation
from ingestion.prompts import load_prompt
from ingestion.rate_limit import GeminiRateLimiter
from utils.types import Config


TITLE_MAX_CHARS = 48
LOGFIRE_DISABLED_VALUES = ("1", "true", "yes")
SYSTEM_PROMPT_NAME = "system_prompt"


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
    message: BaseMessage, *, total_tat_seconds: float | None = None
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
            stats = ChatMessageStats(
                total_tat_seconds=round(total_tat_seconds, 3),
                input_tokens=token_usage["input_tokens"],
                output_tokens=token_usage["output_tokens"],
                total_tokens=token_usage["total_tokens"],
            )
    return ChatMessage(role=role, content=text, stats=stats)


def _logfire_enabled() -> bool:
    return os.environ.get("KIRANA_DISABLE_LOGFIRE", "").lower() not in (
        LOGFIRE_DISABLED_VALUES
    )


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
        or int(input_tokens)
        + int(output_tokens)
    )
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
    }


class ChatService:
    def __init__(
        self,
        *,
        cfg: Config,
        conn: aiosqlite.Connection,
        checkpointer: AsyncSqliteSaver,
    ) -> None:
        self.cfg = cfg
        self.conn = conn
        self.checkpointer = checkpointer
        self.rate_limiter = GeminiRateLimiter(cfg.ingestion.gemini_min_interval_seconds)
        self._models: dict[str, Any] = {}
        self._tools: list[Any] = []
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

    async def create_conversation(self, title: str = "New conversation") -> Conversation:
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
        rows = await self.conn.execute_fetchall(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE id = ? AND is_active = 1
            """,
            (thread_id,),
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

    async def chat(
        self,
        *,
        message: str,
        model_name: str,
        thread_id: str | None,
    ) -> tuple[Conversation, ChatMessage]:
        started_at = time.perf_counter()
        self._validate_model(model_name)
        conversation = await self._ensure_conversation(thread_id, message)
        model_identifier = self.cfg.kirana.model_identifiers[model_name]

        span = nullcontext()
        if _logfire_enabled():
            span = logfire.span(
                "chat_request",
                thread_id=conversation.id,
                model_name=model_name,
                model_identifier=model_identifier,
                query=message,
                query_chars=len(message),
            )

        with span as chat_span:
            logger.info(
                "chat request thread={} model={} chars={} query={!r}",
                conversation.id,
                model_name,
                len(message),
                message,
            )
            if _logfire_enabled():
                logfire.info(
                    "chat query",
                    thread_id=conversation.id,
                    model_name=model_name,
                    model_identifier=model_identifier,
                    query=message,
                    query_chars=len(message),
                )

            if model_routes_via_gemini(model_identifier):
                self.rate_limiter.wait(logger)

            result = await self.graph.ainvoke(
                {"messages": [HumanMessage(content=message)]},
                self._thread_config(conversation.id, model_name=model_name),
            )

            raw_messages: Sequence[BaseMessage] = result.get("messages", [])
            response_message = next(
                (
                    candidate
                    for candidate in reversed(raw_messages)
                    if isinstance(candidate, AIMessage)
                ),
                None,
            )
            if response_message is None:
                raise RuntimeError("model response did not include an assistant message")

            total_tat_seconds = time.perf_counter() - started_at
            response = _message_to_schema(
                response_message, total_tat_seconds=total_tat_seconds
            )
            if response is None:
                raise RuntimeError("model response could not be serialized")

            token_usage = _extract_token_usage(response_message)
            if _logfire_enabled():
                attributes = {
                    "response": response.content,
                    "response_chars": len(response.content),
                    "input_tokens": token_usage["input_tokens"],
                    "output_tokens": token_usage["output_tokens"],
                    "total_tokens": token_usage["total_tokens"],
                    "total_tat_seconds": total_tat_seconds,
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
                )

        response = response
        token_usage = token_usage

        await self._touch_conversation(conversation.id)
        updated = await self.get_conversation(conversation.id)
        if updated is None:
            raise RuntimeError("conversation disappeared during chat request")
        logger.info(
            "chat response thread={} model={} chars={} total_tat_seconds={:.3f} input_tokens={} output_tokens={} total_tokens={} response={!r}",
            conversation.id,
            model_name,
            len(response.content),
            response.stats.total_tat_seconds if response.stats is not None else 0.0,
            token_usage["input_tokens"],
            token_usage["output_tokens"],
            token_usage["total_tokens"],
            response.content,
        )
        return updated, response

    def _build_graph(self) -> Any:
        graph = StateGraph(MessagesState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", ToolNode(self._tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return graph.compile(checkpointer=self.checkpointer)

    async def _agent_node(
        self, state: MessagesState, config: RunnableConfig
    ) -> dict[str, Any]:
        configurable = config.get("configurable", {})
        model_name = configurable.get("model_name")
        if not isinstance(model_name, str):
            model_name = self.cfg.kirana.available_models[0]
        model = self._model(model_name)
        if self._tools:
            model = model.bind_tools(self._tools)
        response = await model.ainvoke(
            [SystemMessage(content=self._system_prompt()), *state["messages"]]
        )
        return {"messages": [response]}

    def _system_prompt(self) -> str:
        prompt = load_prompt(self.cfg.ingestion.prompts_dir, SYSTEM_PROMPT_NAME).strip()
        return f"Today's date is {datetime.now().date().isoformat()}.\n\n{prompt}"

    def _model(self, model_name: str) -> Any:
        self._validate_model(model_name)
        model = self._models.get(model_name)
        if model is None:
            identifier = self.cfg.kirana.model_identifiers[model_name]
            model = build_chat_model(identifier, self.cfg)
            self._models[model_name] = model
        return model

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
        self, thread_id: str, *, model_name: str | None = None
    ) -> dict[str, Any]:
        configurable = {"thread_id": thread_id}
        if model_name is not None:
            configurable["model_name"] = model_name
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
async def chat_service_lifespan(cfg: Config):
    db_path = Path(cfg.kirana.chat_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        checkpointer = AsyncSqliteSaver(conn)
        service = ChatService(cfg=cfg, conn=conn, checkpointer=checkpointer)
        await service.setup()
        yield service

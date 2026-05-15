from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, computed_field

from utils.benchmarks.schemas import (
    AgentTurn,
    BenchmarkTelemetry,
    ChatMessage,
    Conversation,
    RateLimitRetry,
)


class BenchmarkError(RuntimeError):
    """Raised when the benchmark API stream returns an error event."""


class AgentResponse(BaseModel):
    """Response for one benchmark conversation, including cumulative telemetry."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    thread_id: str
    conversation: Conversation
    model: str
    turns: list[AgentTurn] = Field(default_factory=list)

    _client: BenchmarkClient = PrivateAttr()

    @computed_field
    @property
    def content(self) -> str:
        return self.turns[-1].message.content if self.turns else ""

    @computed_field
    @property
    def latest_message(self) -> ChatMessage | None:
        return self.turns[-1].message if self.turns else None

    @computed_field
    @property
    def telemetry(self) -> BenchmarkTelemetry:
        return BenchmarkTelemetry.from_turns(self.turns)

    @property
    def latency_seconds(self) -> float:
        return self.telemetry.latency_seconds

    @property
    def input_tokens(self) -> int:
        return self.telemetry.input_tokens

    @property
    def output_tokens(self) -> int:
        return self.telemetry.output_tokens

    @property
    def total_tokens(self) -> int:
        return self.telemetry.total_tokens

    @property
    def tool_calls(self) -> int:
        return self.telemetry.tool_calls

    @property
    def tools_called(self) -> list[str]:
        return self.telemetry.tools_called

    @property
    def rate_limit_retries(self) -> int:
        return self.telemetry.rate_limit_retries

    def follow_up(self, prompt: str) -> AgentResponse:
        """Send a follow-up turn in the same conversation."""

        return self._client._query(prompt=prompt, thread_id=self.thread_id, prior_turns=self.turns)


class BenchmarkClient:
    """Thin benchmark harness around the Kirana chat streaming API."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        model: str,
        system_prompt: str | None = None,
        timeout: float | httpx.Timeout = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BenchmarkClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def query(self, prompt: str) -> AgentResponse:
        """Start a fresh conversation and return the first agent response."""

        return self._query(prompt=prompt, thread_id=None, prior_turns=[])

    def query_image(self, prompt: str, image_path: str | Path) -> AgentResponse:
        """Start a fresh image conversation and return the first agent response."""

        return self._query_image(
            prompt=prompt,
            image_path=Path(image_path),
            thread_id=None,
            prior_turns=[],
        )

    def _query(
        self,
        *,
        prompt: str,
        thread_id: str | None,
        prior_turns: list[AgentTurn],
    ) -> AgentResponse:
        payload = {
            "message": prompt,
            "model": self.model,
            "thread_id": thread_id,
        }
        if self.system_prompt is not None:
            payload["system_prompt"] = self.system_prompt

        events = list(self._stream_chat_events(payload))
        return self._response_from_events(
            prompt=prompt,
            events=events,
            prior_turns=prior_turns,
        )

    def _query_image(
        self,
        *,
        prompt: str,
        image_path: Path,
        thread_id: str | None,
        prior_turns: list[AgentTurn],
    ) -> AgentResponse:
        events = list(
            self._stream_image_chat_events(
                prompt=prompt,
                image_path=image_path,
                thread_id=thread_id,
            )
        )
        return self._response_from_events(
            prompt=prompt,
            events=events,
            prior_turns=prior_turns,
            image_path=str(image_path),
        )

    def _stream_chat_events(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        with self._client.stream("POST", "/api/chat/stream", json=payload) as response:
            response.raise_for_status()
            yield from _iter_sse_json(response.iter_text())

    def _stream_image_chat_events(
        self,
        *,
        prompt: str,
        image_path: Path,
        thread_id: str | None,
    ) -> Iterator[dict[str, Any]]:
        content_type = (
            mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        )
        data = {"message": prompt, "model": self.model}
        if thread_id is not None:
            data["thread_id"] = thread_id
        if self.system_prompt is not None:
            data["system_prompt"] = self.system_prompt

        with image_path.open("rb") as image_file:
            files = {
                "image": (
                    image_path.name,
                    image_file,
                    content_type,
                )
            }
            with self._client.stream(
                "POST",
                "/api/chat/image/stream",
                data=data,
                files=files,
            ) as response:
                response.raise_for_status()
                yield from _iter_sse_json(response.iter_text())

    def _response_from_events(
        self,
        *,
        prompt: str,
        events: list[dict[str, Any]],
        prior_turns: list[AgentTurn],
        image_path: str | None = None,
    ) -> AgentResponse:
        start_event: dict[str, Any] | None = None
        end_event: dict[str, Any] | None = None
        retry_events: list[RateLimitRetry] = []
        delta_chunks: list[str] = []

        for event in events:
            event_type = event.get("type")
            if event_type == "start":
                start_event = event
            elif event_type == "delta":
                content = event.get("content")
                if isinstance(content, str):
                    delta_chunks.append(content)
            elif event_type == "rate_limit_retry":
                retry_events.append(RateLimitRetry.model_validate(event))
            elif event_type == "end":
                end_event = event
            elif event_type == "error":
                detail = event.get("detail", "unknown benchmark stream error")
                raise BenchmarkError(str(detail))

        if end_event is None:
            raise BenchmarkError("chat stream ended without an end event")

        conversation = Conversation.model_validate(end_event["conversation"])
        thread_id = str(end_event["thread_id"])
        message = ChatMessage.model_validate(end_event["message"])
        if not message.content and delta_chunks:
            message = message.model_copy(update={"content": "".join(delta_chunks)})

        turn = AgentTurn(
            prompt=prompt,
            thread_id=thread_id,
            conversation=conversation,
            message=message,
            image_path=image_path,
            rate_limit_retries=retry_events,
            raw_start_event=start_event or {},
            raw_end_event=end_event,
        )

        agent_response = AgentResponse(
            thread_id=thread_id,
            conversation=conversation,
            model=self.model,
            turns=[*prior_turns, turn],
        )
        agent_response._client = self
        return agent_response


def _iter_sse_json(chunks: Iterator[str]) -> Iterator[dict[str, Any]]:
    data_lines: list[str] = []

    for line in _iter_sse_lines(chunks):
        if not line:
            if data_lines:
                yield _decode_sse_data(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        yield _decode_sse_data(data_lines)


def _iter_sse_lines(chunks: Iterator[str]) -> Iterator[str]:
    pending = ""
    for chunk in chunks:
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield line.rstrip("\r")
    if pending:
        yield pending.rstrip("\r")


def _decode_sse_data(data_lines: list[str]) -> dict[str, Any]:
    try:
        event = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"invalid SSE JSON event: {exc}") from exc
    if not isinstance(event, dict):
        raise BenchmarkError("SSE event payload must be a JSON object")
    return event

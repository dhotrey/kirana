from __future__ import annotations

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ChatMessageStats(BaseModel):
    total_tat_seconds: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: int = 0
    tools: list[str] = Field(default_factory=list)
    rate_limit_retries: int = 0


class ChatMessage(BaseModel):
    role: str
    content: str
    stats: ChatMessageStats | None = None


class RateLimitRetry(BaseModel):
    type: str
    retry_count: int
    retry_attempt: int
    delay_seconds: int
    max_retries: int
    call: str


class AgentTurn(BaseModel):
    prompt: str
    thread_id: str
    conversation: Conversation
    message: ChatMessage
    image_path: str | None = None
    rate_limit_retries: list[RateLimitRetry] = Field(default_factory=list)
    raw_start_event: dict = Field(default_factory=dict)
    raw_end_event: dict = Field(default_factory=dict)


class BenchmarkTelemetry(BaseModel):
    latency_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    tools_called: list[str] = Field(default_factory=list)
    rate_limit_retries: int = 0
    turns: int = 0

    @classmethod
    def from_turns(cls, turns: list[AgentTurn]) -> BenchmarkTelemetry:
        telemetry = cls(turns=len(turns))
        for turn in turns:
            stats = turn.message.stats
            if stats is None:
                continue
            telemetry.latency_seconds += stats.total_tat_seconds
            telemetry.input_tokens += stats.input_tokens
            telemetry.output_tokens += stats.output_tokens
            telemetry.total_tokens += stats.total_tokens
            telemetry.tool_calls += stats.tool_calls
            telemetry.tools_called.extend(stats.tools)
            telemetry.rate_limit_retries += stats.rate_limit_retries
        telemetry.latency_seconds = round(telemetry.latency_seconds, 3)
        return telemetry

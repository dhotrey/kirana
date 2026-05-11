from __future__ import annotations

from pydantic import BaseModel, Field


class ModelOption(BaseModel):
    name: str
    identifier: str


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


class ChatMessage(BaseModel):
    role: str
    content: str
    stats: ChatMessageStats | None = None


class CreateConversationResponse(BaseModel):
    conversation: Conversation


class UpdateConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str
    thread_id: str | None = None

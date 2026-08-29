"""Pydantic schemas for chat."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Chat request body."""

    question: str = Field(min_length=1, max_length=4000)
    stream: bool = Field(default=True)
    conversation_id: str | None = Field(
        default=None,
        description="Session identifier for multi-turn conversation isolation. "
        "When provided, only history from this session is used as context. "
        "When None, all recent (user, kb) history is used.",
    )
    history: list[dict[str, str]] | None = Field(
        default=None,
        description="Previous conversation messages for multi-turn context. "
        "Each dict has 'role' (user/assistant) and 'content'. "
        "If None, the server auto-fetches recent history from DB.",
    )


class ChatSource(BaseModel):
    """Source citation in chat response."""

    chunk_id: str
    doc_id: str
    source: str
    score: float
    text_preview: str


class ChatResponse(BaseModel):
    """Non-streaming chat response."""

    answer: str
    sources: list[ChatSource]
    confidence: float
    tokens_used: int
    latency_ms: int
    refused: bool = False
    refusal_reason: str = ""


class ChatHistoryItem(BaseModel):
    """Chat history item."""

    id: UUID
    kb_id: UUID
    user_id: UUID
    conversation_id: str | None = None
    question: str
    answer: str
    sources: list | dict
    tokens: int
    latency_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}

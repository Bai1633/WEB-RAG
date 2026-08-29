"""Pydantic schemas for knowledge bases."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class KBCreate(BaseModel):
    """Create knowledge base request."""

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    embed_model: str | None = Field(default=None, max_length=255)
    embed_dim: int | None = Field(default=None, ge=1, le=10000)


class KBUpdate(BaseModel):
    """Update knowledge base request."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class KBResponse(BaseModel):
    """Knowledge base response model."""

    id: UUID
    owner_id: UUID
    name: str
    description: str
    embed_model: str
    embed_dim: int
    vector_table: str
    created_at: datetime
    updated_at: datetime
    # Aggregated stats (populated on list/detail; defaults to None elsewhere)
    doc_count: int | None = None
    member_count: int | None = None

    model_config = {"from_attributes": True}


class KBMemberAdd(BaseModel):
    """Add member to KB request."""

    user_email: str
    role: str = Field(pattern="^(owner|editor|viewer)$")


class KBMemberUpdate(BaseModel):
    """Update KB member role request."""

    role: str = Field(pattern="^(owner|editor|viewer)$")


class KBMemberResponse(BaseModel):
    """KB member response."""

    kb_id: UUID
    user_id: UUID
    email: str = ""
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}

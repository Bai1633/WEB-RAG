"""Pydantic schemas for documents."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    """Document response model."""

    id: UUID
    kb_id: UUID
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    status: str
    progress: int
    error: str
    chunk_count: int
    task_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response after document upload (queued for processing)."""

    document_id: UUID
    task_id: str
    status: str = "queued"


class DocumentRetryResponse(BaseModel):
    """Response after retrying a failed document."""

    document_id: UUID
    task_id: str
    status: str = "queued"

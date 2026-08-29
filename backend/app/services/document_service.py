"""Document service - business logic for document upload and processing."""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import aiofiles
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.index_manager import VectorIndexManager
from app.db.models import Document, DocumentStatus
from app.db.repositories.document_repo import DocumentRepository
from app.workers.celery_app import celery_app

settings = get_settings()


class DocumentService:
    """Document service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.vector_index = VectorIndexManager()

    async def upload_document(
        self,
        kb_id: UUID,
        file: UploadFile,
    ) -> Document:
        """Upload a document: stream to disk, create DB record, enqueue Celery task.

        Returns the created Document.
        """
        # Validate MIME type
        mime_type = file.content_type or ""
        if mime_type not in settings.allowed_mime_types_list:
            raise ValueError(f"Unsupported file type: {mime_type}")

        # Validate file size (we'll check again during streaming)
        # Create upload directory structure
        kb_upload_dir = Path(settings.upload_dir) / str(kb_id)
        kb_upload_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        file_ext = Path(file.filename or "").suffix or ""
        stored_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = kb_upload_dir / stored_name

        # Stream file to disk asynchronously (non-blocking event loop)
        file_size = 0
        max_size_bytes = settings.max_file_size_mb * 1024 * 1024

        async with aiofiles.open(file_path, "wb") as f:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    await f.write(b"")  # no-op; unlink below
                    await file.close()
                    file_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"File too large. Maximum size is {settings.max_file_size_mb}MB"
                    )
                await f.write(chunk)

        # Create DB record
        doc = await self.doc_repo.create(
            kb_id=kb_id,
            filename=file.filename or stored_name,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=mime_type,
        )

        # Update status to queued
        doc = await self.doc_repo.update_status(doc.id, DocumentStatus.QUEUED)

        # Enqueue Celery task
        task = celery_app.send_task(
            "app.workers.tasks.process_document",
            args=[str(doc.id), str(kb_id)],
        )

        # Update with task_id
        doc = await self.doc_repo.update_status(
            doc.id,
            DocumentStatus.QUEUED,
            task_id=task.id,
        )

        return doc

    async def get_document(self, doc_id: UUID) -> Document | None:
        """Get a document by ID."""
        return await self.doc_repo.get_by_id(doc_id)

    async def list_documents(
        self,
        kb_id: UUID,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Document]:
        """List documents in a knowledge base."""
        return await self.doc_repo.list_by_kb(kb_id, status=status, skip=skip, limit=limit)

    async def delete_document(self, doc_id: UUID) -> bool:
        """Delete a document and its vectors."""
        doc = await self.doc_repo.get_by_id(doc_id)
        if not doc:
            return False

        # Delete vectors from pgvector
        try:
            await self.vector_index.delete_document_vectors(
                db=self.db,
                kb_id=doc.kb_id,
                doc_id=doc.id,
            )
        except Exception as e:
            # Log but don't fail - the DB record will still be deleted
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to delete vectors for doc {doc_id}: {e}")

        # Delete the file from disk
        try:
            file_path = Path(doc.file_path)
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to delete file for doc {doc_id}: {e}")

        # Revoke Celery task if running
        if doc.task_id:
            with contextlib.suppress(Exception):
                celery_app.control.revoke(doc.task_id, terminate=True)

        # Delete DB record
        return await self.doc_repo.delete(doc_id)

    async def retry_document(self, doc_id: UUID) -> Document:
        """Retry processing a failed document."""
        doc = await self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise ValueError("Document not found")

        if doc.status not in (DocumentStatus.FAILED, DocumentStatus.UPLOADED):
            raise ValueError(f"Cannot retry document with status: {doc.status}")

        # Check file still exists
        if not Path(doc.file_path).exists():
            raise ValueError("Source file no longer exists")

        # Reset status
        doc = await self.doc_repo.update_status(
            doc.id,
            DocumentStatus.QUEUED,
            error="",
            progress=0,
            chunk_count=0,
        )

        # Enqueue new task
        task = celery_app.send_task(
            "app.workers.tasks.process_document",
            args=[str(doc.id), str(doc.kb_id)],
        )

        doc = await self.doc_repo.update_status(
            doc.id,
            DocumentStatus.QUEUED,
            task_id=task.id,
        )

        return doc

    async def get_processing_status(self, doc_id: UUID) -> dict:
        """Get processing status of a document."""
        doc = await self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise ValueError("Document not found")

        result = {
            "id": doc.id,
            "status": doc.status,
            "progress": doc.progress,
            "error": doc.error,
            "chunk_count": doc.chunk_count,
            "task_id": doc.task_id,
        }

        # Try to get Celery task info if available
        if doc.task_id:
            try:
                async_result = celery_app.AsyncResult(doc.task_id)
                result["task_state"] = async_result.state
                if async_result.state == "FAILURE":
                    result["task_error"] = str(async_result.info)
            except Exception:
                pass

        return result

    async def count_documents(self, kb_id: UUID, status: str | None = None) -> int:
        """Count documents in a knowledge base."""
        return await self.doc_repo.count_by_kb(kb_id, status=status)

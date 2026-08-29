"""Document repository - data access layer for documents."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus


class DocumentRepository:
    """Repository for document database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, doc_id: UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == doc_id))
        return result.scalar_one_or_none()

    async def list_by_kb(
        self,
        kb_id: UUID,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[Document]:
        stmt = select(Document).where(Document.kb_id == kb_id)
        if status:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        kb_id: UUID,
        filename: str,
        file_path: str,
        file_size: int,
        mime_type: str,
    ) -> Document:
        doc = Document(
            kb_id=kb_id,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            status=DocumentStatus.UPLOADED,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def update_status(
        self,
        doc_id: UUID,
        status: str,
        progress: int | None = None,
        error: str | None = None,
        chunk_count: int | None = None,
        task_id: str | None = None,
    ) -> Document | None:
        values: dict[str, object] = {"status": status}
        if progress is not None:
            values["progress"] = progress
        if error is not None:
            values["error"] = error
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if task_id is not None:
            values["task_id"] = task_id

        await self.db.execute(
            update(Document).where(Document.id == doc_id).values(**values)
        )
        await self.db.flush()
        return await self.get_by_id(doc_id)

    async def delete(self, doc_id: UUID) -> bool:
        doc = await self.get_by_id(doc_id)
        if doc:
            await self.db.delete(doc)
            await self.db.flush()
            return True
        return False

    async def get_stuck_processing(self, timeout_seconds: int = 3600) -> Sequence[Document]:
        """Get documents stuck in 'processing' status for longer than timeout."""
        import datetime

        cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(Document).where(
                and_(
                    Document.status == DocumentStatus.PROCESSING,
                    Document.updated_at < cutoff,
                )
            )
        )
        return result.scalars().all()

    async def count_by_kb(self, kb_id: UUID, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
        if status:
            stmt = stmt.where(Document.status == status)
        result = await self.db.execute(stmt)
        return result.scalar() or 0

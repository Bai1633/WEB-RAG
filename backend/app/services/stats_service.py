"""Stats service - per-user aggregate statistics for the dashboard."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatHistory, Document
from app.db.repositories.kb_repo import KBRepository

# Documents in these statuses are counted as "in flight" for the dashboard.
_IN_FLIGHT_STATUSES = ("uploaded", "queued", "processing")


class StatsService:
    """Aggregate usage statistics scoped to one user's accessible KBs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.kb_repo = KBRepository(db)

    async def get_user_stats(self, user_id: UUID) -> dict:
        """Return dashboard stats for everything the user can access.

        Documents are aggregated across accessible KBs; chat stats are scoped
        to the user's own history within those KBs.
        """
        kbs = await self.kb_repo.get_accessible_by_user(user_id, skip=0, limit=1000)
        kb_ids = [kb.id for kb in kbs]

        doc_total = doc_completed = doc_in_flight = doc_failed = 0
        chat_rounds = 0
        total_tokens = 0
        chunk_total = 0

        if kb_ids:
            status_rows = await self.db.execute(
                select(Document.status, func.count())
                .where(Document.kb_id.in_(kb_ids))
                .group_by(Document.status)
            )
            status_counts = dict(status_rows.all())
            doc_total = sum(status_counts.values())
            doc_completed = status_counts.get("completed", 0)
            doc_failed = status_counts.get("failed", 0)
            doc_in_flight = sum(status_counts.get(s, 0) for s in _IN_FLIGHT_STATUSES)

            chunk_rows = await self.db.execute(
                select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                    Document.kb_id.in_(kb_ids)
                )
            )
            chunk_total = int(chunk_rows.scalar() or 0)

            chat_rows = await self.db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(ChatHistory.tokens), 0),
                ).where(
                    ChatHistory.user_id == user_id,
                    ChatHistory.kb_id.in_(kb_ids),
                )
            )
            chat_rounds, total_tokens = chat_rows.one()
            chat_rounds = int(chat_rounds or 0)
            total_tokens = int(total_tokens or 0)

        return {
            "knowledge_bases": len(kb_ids),
            "documents": {
                "total": doc_total,
                "completed": doc_completed,
                "in_flight": doc_in_flight,
                "failed": doc_failed,
            },
            "chunks": chunk_total,
            "chat_rounds": chat_rounds,
            "total_tokens": total_tokens,
        }

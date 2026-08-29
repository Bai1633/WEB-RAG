"""Chat history repository - data access layer for chat histories."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatHistory


class ChatRepository:
    """Repository for chat history database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, chat_id: UUID) -> ChatHistory | None:
        result = await self.db.execute(select(ChatHistory).where(ChatHistory.id == chat_id))
        return result.scalar_one_or_none()

    async def list_by_user_and_kb(
        self,
        user_id: UUID,
        kb_id: UUID,
        skip: int = 0,
        limit: int = 50,
        conversation_id: str | None = None,
    ) -> Sequence[ChatHistory]:
        conditions = [
            ChatHistory.user_id == user_id,
            ChatHistory.kb_id == kb_id,
        ]
        if conversation_id is not None:
            conditions.append(ChatHistory.conversation_id == conversation_id)
        result = await self.db.execute(
            select(ChatHistory)
            .where(*conditions)
            .order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def count_by_user_and_kb(
        self, user_id: UUID, kb_id: UUID, conversation_id: str | None = None
    ) -> int:
        """Count chat history entries for a user and KB."""
        conditions = [
            ChatHistory.user_id == user_id,
            ChatHistory.kb_id == kb_id,
        ]
        if conversation_id is not None:
            conditions.append(ChatHistory.conversation_id == conversation_id)
        result = await self.db.execute(
            select(func.count())
            .select_from(ChatHistory)
            .where(*conditions)
        )
        return result.scalar() or 0

    async def create(
        self,
        kb_id: UUID,
        user_id: UUID,
        question: str,
        answer: str,
        sources: list | dict | None = None,
        tokens: int = 0,
        latency_ms: int = 0,
        conversation_id: str | None = None,
    ) -> ChatHistory:
        chat = ChatHistory(
            kb_id=kb_id,
            user_id=user_id,
            question=question,
            answer=answer,
            sources=sources or [],
            tokens=tokens,
            latency_ms=latency_ms,
            conversation_id=conversation_id,
        )
        self.db.add(chat)
        await self.db.flush()
        await self.db.refresh(chat)
        return chat

    async def delete(self, chat_id: UUID) -> bool:
        chat = await self.get_by_id(chat_id)
        if chat:
            await self.db.delete(chat)
            await self.db.flush()
            return True
        return False

    async def delete_by_conversation_id(
        self, user_id: UUID, kb_id: UUID, conversation_id: str
    ) -> int:
        """Delete all chat history entries for a specific conversation."""
        from sqlalchemy import delete

        result = await self.db.execute(
            delete(ChatHistory).where(
                ChatHistory.user_id == user_id,
                ChatHistory.kb_id == kb_id,
                ChatHistory.conversation_id == conversation_id,
            )
        )
        await self.db.flush()
        return result.rowcount

    async def list_conversation_ids(
        self, user_id: UUID, kb_id: UUID
    ) -> list[dict]:
        """List distinct conversation IDs with their latest question and time."""
        result = await self.db.execute(
            select(
                ChatHistory.conversation_id,
                func.max(ChatHistory.created_at).label("last_active"),
                func.count(ChatHistory.id).label("rounds"),
            )
            .where(
                ChatHistory.user_id == user_id,
                ChatHistory.kb_id == kb_id,
                ChatHistory.conversation_id.isnot(None),
            )
            .group_by(ChatHistory.conversation_id)
            .order_by(func.max(ChatHistory.created_at).desc())
        )
        return [
            {
                "conversation_id": row.conversation_id,
                "last_active": row.last_active.isoformat(),
                "rounds": row.rounds,
            }
            for row in result.fetchall()
        ]

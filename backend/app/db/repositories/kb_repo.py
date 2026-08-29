"""Knowledge base repository - data access layer for knowledge bases."""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import Document, KBMember, KnowledgeBase


class KBRepository:
    """Repository for knowledge base database operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, kb_id: UUID) -> KnowledgeBase | None:
        result = await self.db.execute(
            select(KnowledgeBase)
            .options(joinedload(KnowledgeBase.owner))
            .where(KnowledgeBase.id == kb_id)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: UUID, skip: int = 0, limit: int = 100) -> Sequence[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.owner_id == owner_id)
            .order_by(KnowledgeBase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def count_by_owner(self, owner_id: UUID) -> int:
        """Count knowledge bases owned by a user."""
        result = await self.db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.owner_id == owner_id)
        )
        return result.scalar() or 0

    async def get_accessible_by_user(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[KnowledgeBase]:
        """List all KBs accessible by a user (owner + member).

        Uses a UNION of owned KBs and member KBs to avoid duplicates
        when the user is both owner and member (owner is always a member).
        """
        owned = select(KnowledgeBase.id).where(KnowledgeBase.owner_id == user_id)
        member = select(KBMember.kb_id).where(KBMember.user_id == user_id)
        kb_ids_subq = select(union_all(owned, member).subquery().c.id).distinct().subquery()

        result = await self.db.execute(
            select(KnowledgeBase)
            .options(joinedload(KnowledgeBase.owner))
            .where(KnowledgeBase.id.in_(kb_ids_subq))
            .order_by(KnowledgeBase.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def count_accessible_by_user(self, user_id: UUID) -> int:
        """Count all KBs accessible by a user (owner + member)."""
        owned = select(KnowledgeBase.id).where(KnowledgeBase.owner_id == user_id)
        member = select(KBMember.kb_id).where(KBMember.user_id == user_id)
        kb_ids_subq = select(union_all(owned, member).subquery().c.id).distinct().subquery()

        result = await self.db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.id.in_(kb_ids_subq))
        )
        return result.scalar() or 0

    async def count_documents_by_kbs(self, kb_ids: Iterable[UUID]) -> dict[UUID, int]:
        """Return {kb_id: doc_count} for the given KBs in a single query."""
        kb_ids = list(kb_ids)
        if not kb_ids:
            return {}
        result = await self.db.execute(
            select(Document.kb_id, func.count())
            .where(Document.kb_id.in_(kb_ids))
            .group_by(Document.kb_id)
        )
        return dict(result.all())

    async def count_members_by_kbs(self, kb_ids: Iterable[UUID]) -> dict[UUID, int]:
        """Return {kb_id: member_count} for the given KBs in a single query."""
        kb_ids = list(kb_ids)
        if not kb_ids:
            return {}
        result = await self.db.execute(
            select(KBMember.kb_id, func.count())
            .where(KBMember.kb_id.in_(kb_ids))
            .group_by(KBMember.kb_id)
        )
        return dict(result.all())

    async def get_user_roles_by_kbs(
        self, user_id: UUID, kb_ids: Iterable[UUID]
    ) -> dict[UUID, str]:
        """Return {kb_id: role} for a given user across the given KBs.

        Owners are always resolved to ``KBRole.OWNER`` even when no explicit
        ``kb_members`` row exists (owner membership is implicit by ownership).
        """
        from app.db.models import KBRole

        kb_ids = list(kb_ids)
        roles: dict[UUID, str] = {}

        # Explicit memberships
        if kb_ids:
            rows = await self.db.execute(
                select(KBMember.kb_id, KBMember.role).where(
                    KBMember.user_id == user_id,
                    KBMember.kb_id.in_(kb_ids),
                )
            )
            roles.update(dict(rows.all()))

        # Implicit owner roles
        owned = await self.db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.owner_id == user_id,
                KnowledgeBase.id.in_(kb_ids) if kb_ids else True,
            )
        )
        for (kb_id,) in owned.all():
            roles[kb_id] = KBRole.OWNER

        return roles

    async def create(
        self,
        owner_id: UUID,
        name: str,
        description: str,
        embed_model: str,
        embed_dim: int,
        vector_table: str,
    ) -> KnowledgeBase:
        kb = KnowledgeBase(
            owner_id=owner_id,
            name=name,
            description=description,
            embed_model=embed_model,
            embed_dim=embed_dim,
            vector_table=vector_table,
        )
        self.db.add(kb)
        await self.db.flush()
        await self.db.refresh(kb)
        return kb

    async def update(self, kb_id: UUID, **kwargs: object) -> KnowledgeBase | None:
        kb = await self.get_by_id(kb_id)
        if kb:
            for key, value in kwargs.items():
                if hasattr(kb, key):
                    setattr(kb, key, value)
            await self.db.flush()
            await self.db.refresh(kb)
        return kb

    async def delete(self, kb_id: UUID) -> bool:
        kb = await self.get_by_id(kb_id)
        if kb:
            await self.db.delete(kb)
            await self.db.flush()
            return True
        return False

    # ===== Member (RBAC) operations =====

    async def get_member(self, kb_id: UUID, user_id: UUID) -> KBMember | None:
        result = await self.db.execute(
            select(KBMember).where(
                KBMember.kb_id == kb_id,
                KBMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_member(self, kb_id: UUID, user_id: UUID, role: str) -> KBMember:
        member = KBMember(kb_id=kb_id, user_id=user_id, role=role)
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def update_member_role(self, kb_id: UUID, user_id: UUID, role: str) -> KBMember | None:
        member = await self.get_member(kb_id, user_id)
        if member:
            member.role = role
            await self.db.flush()
            await self.db.refresh(member)
        return member

    async def remove_member(self, kb_id: UUID, user_id: UUID) -> bool:
        member = await self.get_member(kb_id, user_id)
        if member:
            await self.db.delete(member)
            await self.db.flush()
            return True
        return False

    async def list_members(self, kb_id: UUID) -> Sequence[KBMember]:
        result = await self.db.execute(
            select(KBMember)
            .options(joinedload(KBMember.user))
            .where(KBMember.kb_id == kb_id)
            .order_by(KBMember.created_at.asc())
        )
        return result.scalars().all()

"""Knowledge base service - business logic for KB CRUD and RBAC."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.index_manager import VectorIndexManager
from app.db.models import KBRole, KnowledgeBase
from app.db.repositories.kb_repo import KBRepository
from app.db.repositories.user_repo import UserRepository

settings = get_settings()


class KBService:
    """Knowledge base service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.kb_repo = KBRepository(db)
        self.user_repo = UserRepository(db)
        self.vector_index = VectorIndexManager()

    async def create_kb(
        self,
        owner_id: UUID,
        name: str,
        description: str,
        embed_model: str | None = None,
        embed_dim: int | None = None,
    ) -> KnowledgeBase:
        """Create a new knowledge base with its own vector table."""
        effective_embed_model = embed_model or settings.embedding_model_name
        effective_embed_dim = embed_dim or settings.embedding_dim

        # First create the KB record to get a real UUID, then derive vector_table name
        kb = await self.kb_repo.create(
            owner_id=owner_id,
            name=name,
            description=description,
            embed_model=effective_embed_model,
            embed_dim=effective_embed_dim,
            vector_table="",  # placeholder, updated below
        )

        # Use kb.id (not a random temp_id) to generate the vector table name
        vector_table = f"vectors_{kb.id.hex}"
        await self.kb_repo.update(kb.id, vector_table=vector_table)

        await self.vector_index.create_vector_table(
            db=self.db,
            kb_id=kb.id,
            embed_dim=effective_embed_dim,
        )

        await self.kb_repo.add_member(
            kb_id=kb.id,
            user_id=owner_id,
            role=KBRole.OWNER,
        )

        return kb

    async def get_kb(self, kb_id: UUID) -> KnowledgeBase | None:
        """Get a knowledge base by ID."""
        return await self.kb_repo.get_by_id(kb_id)

    async def list_user_kbs(self, user_id: UUID, skip: int = 0, limit: int = 100) -> Sequence[KnowledgeBase]:
        """List all knowledge bases accessible by a user (owner + member)."""
        return await self.kb_repo.get_accessible_by_user(user_id, skip=skip, limit=limit)

    async def count_user_kbs(self, user_id: UUID) -> int:
        """Count all knowledge bases accessible by a user (owner + member)."""
        return await self.kb_repo.count_accessible_by_user(user_id)

    async def list_user_kbs_with_stats(
        self, user_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[dict]:
        """List accessible KBs enriched with doc_count and member_count."""
        kbs = await self.list_user_kbs(user_id, skip=skip, limit=limit)
        if not kbs:
            return []
        kb_ids = [kb.id for kb in kbs]
        doc_counts = await self.kb_repo.count_documents_by_kbs(kb_ids)
        member_counts = await self.kb_repo.count_members_by_kbs(kb_ids)
        user_roles = await self.kb_repo.get_user_roles_by_kbs(user_id, kb_ids)
        return [
            {
                "id": kb.id,
                "owner_id": kb.owner_id,
                "name": kb.name,
                "description": kb.description,
                "embed_model": kb.embed_model,
                "embed_dim": kb.embed_dim,
                "vector_table": kb.vector_table,
                "created_at": kb.created_at,
                "updated_at": kb.updated_at,
                "doc_count": doc_counts.get(kb.id, 0),
                "member_count": member_counts.get(kb.id, 0),
                "role": user_roles.get(kb.id) or KBRole.VIEWER,
            }
            for kb in kbs
        ]

    async def update_kb(
        self,
        kb_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeBase | None:
        """Update a knowledge base."""
        updates: dict[str, object] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if not updates:
            return await self.get_kb(kb_id)
        return await self.kb_repo.update(kb_id, **updates)

    async def delete_kb(self, kb_id: UUID) -> bool:
        """Delete a knowledge base and its vector table."""
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            return False

        await self.vector_index.drop_vector_table(db=self.db, kb_id=kb.id)

        return await self.kb_repo.delete(kb_id)

    # ===== Stats =====

    async def count_documents(self, kb_id: UUID) -> int:
        """Count documents in a knowledge base."""
        counts = await self.kb_repo.count_documents_by_kbs([kb_id])
        return counts.get(kb_id, 0)

    async def count_members(self, kb_id: UUID) -> int:
        """Count members of a knowledge base."""
        counts = await self.kb_repo.count_members_by_kbs([kb_id])
        return counts.get(kb_id, 0)

    # ===== RBAC =====

    async def check_permission(
        self,
        kb_id: UUID,
        user_id: UUID,
        required_role: str,
    ) -> bool:
        """Check if a user has the required role for a KB.

        Role hierarchy: owner > editor > viewer
        """
        role_order = {KBRole.VIEWER: 1, KBRole.EDITOR: 2, KBRole.OWNER: 3}
        required_level = role_order.get(required_role, 0)

        member = await self.kb_repo.get_member(kb_id, user_id)
        if not member:
            kb = await self.kb_repo.get_by_id(kb_id)
            return bool(kb and kb.owner_id == user_id)

        user_level = role_order.get(member.role, 0)
        return user_level >= required_level

    async def get_user_role(self, kb_id: UUID, user_id: UUID) -> str | None:
        """Get a user's role in a KB."""
        kb = await self.kb_repo.get_by_id(kb_id)
        if kb and kb.owner_id == user_id:
            return KBRole.OWNER
        member = await self.kb_repo.get_member(kb_id, user_id)
        return member.role if member else None

    async def add_member(self, kb_id: UUID, user_email: str, role: str) -> tuple[UUID, str]:
        """Add a member to a KB by email. Returns (user_id, role)."""
        user = await self.user_repo.get_by_email(user_email)
        if not user:
            raise ValueError("User not found")

        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise ValueError("Knowledge base not found")

        if kb.owner_id == user.id:
            raise ValueError("Cannot add owner as member")

        existing = await self.kb_repo.get_member(kb_id, user.id)
        if existing:
            raise ValueError("User is already a member")

        member = await self.kb_repo.add_member(kb_id=kb_id, user_id=user.id, role=role)
        return member.user_id, member.role

    async def update_member_role(self, kb_id: UUID, user_id: UUID, role: str) -> str | None:
        """Update a member's role."""
        member = await self.kb_repo.update_member_role(kb_id, user_id, role)
        return member.role if member else None

    async def remove_member(self, kb_id: UUID, user_id: UUID) -> bool:
        """Remove a member from a KB."""
        kb = await self.kb_repo.get_by_id(kb_id)
        if kb and kb.owner_id == user_id:
            raise ValueError("Cannot remove owner")
        return await self.kb_repo.remove_member(kb_id, user_id)

    async def list_members(self, kb_id: UUID):
        """List all members of a KB."""
        return await self.kb_repo.list_members(kb_id)

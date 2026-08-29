"""Vector index manager - dynamic vector table creation, deletion, and dimension validation.

Each knowledge base has its own vector table: vectors_<kb_uuid>
This module handles all pgvector table operations.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class VectorIndexManager:
    """Manages per-KB vector tables in PostgreSQL with pgvector."""

    @staticmethod
    def _table_name(kb_id: UUID) -> str:
        """Generate vector table name for a knowledge base."""
        table_name = f"vectors_{kb_id.hex}"
        if not table_name.isidentifier():
            raise ValueError(f"Invalid table name: {table_name}")
        return table_name

    @staticmethod
    def table_name_from_str(kb_id: str) -> str:
        """Generate vector table name from string UUID.

        Raises ValueError if the generated table name is not a valid identifier.
        """
        table_name = f"vectors_{UUID(kb_id).hex}"
        if not table_name.isidentifier():
            raise ValueError(f"Invalid table name: {table_name}")
        return table_name

    async def create_vector_table(
        self,
        db: AsyncSession,
        kb_id: UUID,
        embed_dim: int,
    ) -> str:
        """Create a new vector table for a knowledge base.

        Returns the table name.
        """
        table_name = self._table_name(kb_id)

        # Enable pg_trgm extension (idempotent) for the hybrid lexical retrieval.
        # Requires the DB role to be superuser (typical for docker postgres).
        # If unavailable or not permitted, we degrade gracefully: skip the trigram
        # index and keep the table usable for pure vector retrieval.
        trgm_supported = True
        try:
            await db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        except Exception as e:  # pragma: no cover - permission dependent
            logger.warning("pg_trgm_extension_unavailable", error=str(e))
            trgm_supported = False

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                doc_id UUID NOT NULL,
                kb_id UUID NOT NULL,
                text TEXT NOT NULL,
                metadata JSONB DEFAULT '{{}}'::jsonb,
                embedding vector({embed_dim}) NOT NULL
            )
        """
        await db.execute(text(create_sql))

        # trigram index on text for the lexical (word-match) retrieval channel.
        # Powers `similarity()` / `%` operators used by hybrid RRF fusion.
        if trgm_supported:
            try:
                trgm_sql = f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_text_gin
                    ON {table_name}
                    USING gin (text gin_trgm_ops)
                """
                await db.execute(text(trgm_sql))
            except Exception as e:  # pragma: no cover - ops dependent
                logger.warning("pg_trgm_index_unavailable", error=str(e))

        # Full-text channel: tsvector generated column + GIN index.
        # GENERATED ALWAYS AS ... STORED is supported on PG 12+. The ALTER is
        # idempotent so existing tables get the column on next startup.
        try:
            tsv_col_sql = f"""
                ALTER TABLE {table_name}
                ADD COLUMN IF NOT EXISTS tsv tsvector
                GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
            """
            await db.execute(text(tsv_col_sql))

            tsv_idx_sql = f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_tsv_gin
                ON {table_name}
                USING gin (tsv)
            """
            await db.execute(text(tsv_idx_sql))
        except Exception as e:  # pragma: no cover - ops dependent
            logger.warning("tsvector_channel_unavailable", error=str(e))

        index_sql = f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_doc_id
            ON {table_name} (doc_id)
        """
        await db.execute(text(index_sql))

        kb_index_sql = f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_kb_id
            ON {table_name} (kb_id)
        """
        await db.execute(text(kb_index_sql))

        hnsw_sql = f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_embedding
            ON {table_name}
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 200)
        """
        await db.execute(text(hnsw_sql))

        await db.commit()
        return table_name

    async def drop_vector_table(self, db: AsyncSession, kb_id: UUID) -> None:
        """Drop the vector table for a knowledge base."""
        table_name = self._table_name(kb_id)
        await db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        await db.commit()

    async def delete_document_vectors(
        self,
        db: AsyncSession,
        kb_id: UUID,
        doc_id: UUID,
    ) -> int:
        """Delete all vectors for a specific document. Returns count of deleted rows."""
        table_name = self._table_name(kb_id)

        result = await db.execute(
            text(f"DELETE FROM {table_name} WHERE doc_id = :doc_id"),
            {"doc_id": doc_id},
        )
        await db.commit()
        return result.rowcount or 0

    async def verify_dimension(
        self,
        db: AsyncSession,
        kb_id: UUID,
        expected_dim: int,
    ) -> bool:
        """Verify that the vector table has the expected embedding dimension.

        Returns True if dimension matches, False otherwise.
        """
        table_name = self._table_name(kb_id)

        check_sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = :table_name
            )
        """
        result = await db.execute(text(check_sql), {"table_name": table_name})
        exists = result.scalar()
        if not exists:
            return False

        dim_sql = """
            SELECT atttypmod
            FROM pg_attribute
            WHERE attrelid = :table_name::regclass
              AND attname = 'embedding'
        """
        result = await db.execute(text(dim_sql), {"table_name": table_name})
        atttypmod = result.scalar()
        if atttypmod is None or atttypmod <= 0:
            return False

        return atttypmod == expected_dim

    async def table_exists(self, db: AsyncSession, kb_id: UUID) -> bool:
        """Check if the vector table for a knowledge base exists."""
        table_name = self._table_name(kb_id)
        check_sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = :table_name
            )
        """
        result = await db.execute(text(check_sql), {"table_name": table_name})
        return bool(result.scalar())

    async def count_vectors(
        self,
        db: AsyncSession,
        kb_id: UUID,
        doc_id: UUID | None = None,
    ) -> int:
        """Count vectors in a KB's vector table, optionally filtered by doc_id."""
        table_name = self._table_name(kb_id)

        if doc_id:
            sql = f"SELECT COUNT(*) FROM {table_name} WHERE doc_id = :doc_id"
            result = await db.execute(text(sql), {"doc_id": doc_id})
        else:
            sql = f"SELECT COUNT(*) FROM {table_name}"
            result = await db.execute(text(sql))

        return result.scalar() or 0

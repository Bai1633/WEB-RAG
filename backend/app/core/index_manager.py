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
        # 注意：检索侧用的是 word_similarity(query, text) 函数形式，走不到这个
        # gin_trgm_ops 索引（索引只服务 <% / %> 算子）。单表规模小，正确性优先；
        # 表变大后应改为 `WHERE :q <% text` 并设置 pg_trgm.word_similarity_threshold。
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
        await self._ensure_fulltext_column(db, table_name)

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

    # 中文全文检索用的切分函数：在每个 CJK 字符后插一个空格，再交给 to_tsvector。
    #
    # 为什么必须这么做：PG 的 'simple' 配置**不做中文分词**（只按空格/标点切分），
    # 整句中文会被当成一个大 token。于是 `tsv @@ websearch_to_tsquery('simple', '整句中文')`
    # 永远为 false —— 2026-09-10 实测：库里 9 条中文 chunk，连查询词
    # `'聊斋 剧本 大纲'` 都是 0 命中（文档里是"剧本大纲"，无法拆成"剧本"+"大纲"）。
    # 逐字切分后，索引侧变成单字 lexeme，查询侧用单字 OR 匹配，词法召回立刻恢复
    # （同一测试：0 命中 → 6 命中）。
    #
    # 标记为 IMMUTABLE 是 PG 对生成列表达式的硬性要求；只用到不可变的
    # regexp_replace / to_tsvector，语义上确实不可变。
    _CJK_TSV_FUNCTION_SQL = r"""
        CREATE OR REPLACE FUNCTION rag_cjk_tsv(txt text) RETURNS tsvector
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT to_tsvector(
                'simple',
                regexp_replace(
                    coalesce(txt, ''),
                    '([\u2e80-\u9fff\uff00-\uffef])',
                    '\1 ',
                    'g'
                )
            )
        $$
    """

    _CJK_TSV_EXPR = "rag_cjk_tsv(text)"

    async def _ensure_fulltext_column(self, db: AsyncSession, table_name: str) -> None:
        """确保 tsv 生成列存在，且用的是"中文逐字切分"表达式。

        历史包袱：早期版本建的是 ``to_tsvector('simple', text)``，对中文完全无效。
        PG 不允许修改生成列的表达式，只能 DROP 再 ADD —— 这会触发全表重写，
        顺带把已有数据全部回填成新表达式的结果，所以不需要单独的迁移脚本。
        检测到表达式已经是正确的（含 rag_cjk_tsv）则跳过，保证幂等。
        """
        try:
            await db.execute(text(self._CJK_TSV_FUNCTION_SQL))

            existing = (
                await db.execute(
                    text(
                        """
                        SELECT pg_get_expr(d.adbin, d.adrelid) AS gen_expr,
                               a.attgenerated
                        FROM pg_attribute a
                        LEFT JOIN pg_attrdef d
                               ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                        WHERE a.attrelid = CAST(:tbl AS regclass)
                          AND a.attname = 'tsv'
                          AND NOT a.attisdropped
                        """
                    ),
                    {"tbl": table_name},
                )
            ).first()

            needs_rebuild = True
            if existing is not None:
                gen_expr = existing[0] or ""
                is_generated = existing[1] == "s"
                if is_generated and "rag_cjk_tsv" in gen_expr:
                    needs_rebuild = False
                    logger.debug("fulltext_column_up_to_date", table=table_name)
                else:
                    # 旧表达式（对中文无效）⇒ 必须重建；非生成列（历史手写）同理。
                    logger.info(
                        "fulltext_column_rebuild",
                        table=table_name,
                        old_expr=gen_expr[:120],
                    )
                    await db.execute(
                        text(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS tsv")
                    )

            if needs_rebuild:
                await db.execute(
                    text(
                        f"""
                        ALTER TABLE {table_name}
                        ADD COLUMN tsv tsvector
                        GENERATED ALWAYS AS ({self._CJK_TSV_EXPR}) STORED
                        """
                    )
                )

            await db.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_tsv_gin
                    ON {table_name}
                    USING gin (tsv)
                    """
                )
            )
        except Exception as e:  # pragma: no cover - ops dependent
            logger.warning("tsvector_channel_unavailable", error=str(e))

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

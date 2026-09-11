"""RAG Engine - hybrid retrieval, reranking, streaming generation with confidence gating.

Key features:
- Vector + BM25 hybrid retrieval (vector-only for now, BM25 added later)
- BGE reranker for re-ranking
- Confidence threshold gating (拒答)
- Streaming generation with source citations
- All blocking operations use asyncio.to_thread to avoid blocking event loop
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text as sa_text  # alias: 避免与下方循环里的局部变量 text(切片文本) 冲突
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding import get_embedding_provider
from app.core.index_manager import VectorIndexManager
from app.core.llm import get_llm_provider

settings = get_settings()
logger = structlog.get_logger()


@dataclass
class RetrievedChunk:
    """A retrieved chunk with metadata and relevance score."""

    chunk_id: str
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0  # higher = more relevant
    source: str = ""
    # Which retrieval channels matched this chunk: {"vector","lexical","fulltext"}
    channels: list[str] = field(default_factory=list)
    # 未归一化的 RRF 融合原始分。score 会被 max 归一化（top1 恒为 1.0）或被重排
    # sigmoid 覆盖，都会丢失"绝对相关度"信息；下游若要判断"召回质量如何"应看这个值。
    fused_score: float = 0.0
    # 重排模型给出的原始 logit（未过 sigmoid），仅在重排生效时填充。
    reranker_logit: float | None = None


@dataclass
class RAGResponse:
    """Complete RAG response."""

    answer: str
    sources: list[RetrievedChunk]
    confidence: float
    tokens_used: int
    latency_ms: int
    refused: bool = False
    refusal_reason: str = ""


class RAGEngine:
    """RAG engine with hybrid retrieval, reranking, and streaming generation."""

    _DEFAULT_SYSTEM_PROMPT = """你是一个专业的知识库问答助手。请基于提供的上下文信息回答用户的问题。

规则：
1. 只使用上下文中提供的信息，不要编造内容
2. 如果上下文中没有答案，请明确说"根据知识库中的信息，我无法回答这个问题"
3. 回答要简洁、准确、有条理
4. 引用来源时可以在句末标注 [来源: 文件名]
5. 对于表格数据，请清晰地呈现
"""

    _DEFAULT_REFUSAL = (
        "根据知识库中的信息，我无法回答这个问题。请尝试换一种提问方式，"
        "或者确认相关文档是否已上传到知识库。"
    )
    _refusal_tokens: int | None = None  # lazily computed once

    def __init__(self) -> None:
        self._vector_index = VectorIndexManager()
        # 支持通过环境变量 SYSTEM_PROMPT 覆盖系统提示词；留空则使用内置默认台词。
        self._system_prompt = settings.system_prompt or self._DEFAULT_SYSTEM_PROMPT

    async def query(
        self,
        db: AsyncSession,
        kb_id: UUID,
        question: str,
        stream: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> RAGResponse | AsyncGenerator[str, None]:
        """Query the RAG engine.

        Args:
            db: Async database session.
            kb_id: Knowledge base ID.
            question: User question.
            stream: Whether to stream the response.
            history: Previous conversation messages (role/content pairs)
                     for multi-turn context. Last N rounds from the same KB.

        Returns:
            RAGResponse if stream=False, async generator of strings if stream=True.
        """
        start_time = time.time()

        # Step 0: Multi-turn query rewrite. Follow-up questions like "它多少钱？"
        # retrieve poorly when embedded verbatim; condense history + question into
        # a standalone query for retrieval/rerank, keep the original for generation.
        retrieve_query = question
        if history and settings.query_rewrite_enabled:
            retrieve_query = await self.rewrite_query(question, history)

        reranked_chunks = await self.retrieve(db, kb_id, retrieve_query)

        # Step 4: Confidence check
        refusal_answer = (
            "根据知识库中的信息，我无法回答这个问题。请尝试换一种提问方式，"
            "或者确认相关文档是否已上传到知识库。"
        )
        # 拒答判据（2026-09-10 修订）
        # 主判据 = 召回为空：这是唯一语义明确、且不受分数口径影响的信号。
        # 绝对阈值仅在 confidence_gate_enabled=True 时额外启用，默认关闭 —— 因为
        # score 在两条路径下都不适合做绝对判断（详见 config.py 里的注释）：
        #   关重排 → _rrf_fuse 做了 max 归一化，top1 恒为 1.0，阈值形同虚设；
        #   开重排 → score 是 BGE sigmoid 绝对值，"总结/归纳"类元问题天然只有
        #            0.002~0.005，用 0.35 去卡必然把正常提问误杀成拒答。
        below_threshold = bool(
            settings.confidence_gate_enabled
            and reranked_chunks
            and reranked_chunks[0].score < settings.confidence_threshold
        )
        if not reranked_chunks or below_threshold:
            if stream:
                # 流式请求必须始终返回异步生成器，否则 ChatService._chat_stream 的
                # `async for chunk in stream_gen` 会因拿到 RAGResponse 而失败
                # (assert hasattr(stream_gen, "__aiter__") -> AssertionError)。
                return self._generate_refusal_stream(refusal_answer, start_time)
            latency_ms = int((time.time() - start_time) * 1000)
            return RAGResponse(
                answer=refusal_answer,
                sources=[],
                confidence=0.0,
                tokens_used=0,
                latency_ms=latency_ms,
                refused=True,
                refusal_reason=(
                    "no_results"
                    if not reranked_chunks
                    else "below_confidence_threshold"
                ),
            )

        top_confidence = reranked_chunks[0].score

        # Step 5: Build context
        context = self._build_context(reranked_chunks)

        # Step 6: Generate answer
        if stream:
            return self._generate_stream(question, context, reranked_chunks, start_time, history)
        else:
            answer, tokens = await self._generate(question, context, history)
            latency_ms = int((time.time() - start_time) * 1000)
            return RAGResponse(
                answer=answer,
                sources=reranked_chunks,
                confidence=top_confidence,
                tokens_used=tokens,
                latency_ms=latency_ms,
            )

    async def retrieve(
        self,
        db: AsyncSession,
        kb_id: UUID,
        query: str,
    ) -> list[RetrievedChunk]:
        """Full retrieval pipeline: embed -> hybrid search -> rerank.

        Public entry point so the eval harness and tests can measure retrieval
        quality without invoking LLM generation.
        """
        query_embedding = await self._embed_query(query)
        chunks = await self._retrieve_chunks(db, kb_id, query_embedding, query)
        return await self._rerank_chunks(query, chunks)

    async def _embed_query(self, question: str) -> list[float]:
        """Embed the question. Run in thread to avoid blocking event loop."""

        def _embed() -> list[float]:
            provider = get_embedding_provider()
            embeddings = provider.get_embeddings([question])
            return embeddings[0] if embeddings else []

        return await asyncio.to_thread(_embed)

    _REWRITE_SYSTEM_PROMPT = (
        "你是一个检索查询改写器。给定对话历史和用户的追问，把追问改写成一个"
        "不依赖上下文、可直接用于知识库检索的独立完整问题。\n"
        "规则：\n"
        "1. 只输出改写后的问题本身，不要任何解释、前缀或引号\n"
        "2. 把指代（它/这个/上面提到的…）补全为具体对象\n"
        "3. 保留用户提问的语言（中文问改写为中文，英文问改写为英文）\n"
        "4. 如果追问本身已是独立完整的问题，原样输出"
    )

    async def rewrite_query(
        self,
        question: str,
        history: list[dict[str, str]],
        max_history_messages: int = 6,
    ) -> str:
        """Condense conversation history + a follow-up question into a
        standalone retrieval query.

        Best-effort: any failure (LLM error, empty/oversized output) falls back
        to the original question so the chat flow is never blocked by rewriting.
        """
        try:
            llm = get_llm_provider()
            recent = history[-max_history_messages:]
            history_text = "\n".join(
                f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
                for m in recent
            )
            messages = [
                {"role": "system", "content": self._REWRITE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"对话历史：\n{history_text}\n\n"
                        f"用户追问：{question}\n\n改写后的独立问题："
                    ),
                },
            ]
            rewritten, _ = await llm.chat(messages, max_tokens=128, temperature=0.0)
            # Take the first non-empty line, then strip wrapping quotes.
            first_line = next(
                (ln.strip() for ln in rewritten.strip().splitlines() if ln.strip()), ""
            )
            rewritten = first_line.strip("\"'")
            if not rewritten or len(rewritten) > 500:
                return question
            if rewritten != question:
                logger.info("query_rewritten", original=question, rewritten=rewritten)
            return rewritten
        except Exception as e:
            logger.warning("query_rewrite_failed", error=str(e), fallback=True)
            return question

    async def _retrieve_chunks(
        self,
        db: AsyncSession,
        kb_id: UUID,
        query_embedding: list[float],
        question: str = "",
    ) -> list[RetrievedChunk]:
        """Hybrid retrieval: vector + trigram lexical + tsvector full-text.

        Runs the enabled channels in parallel, then fuses their ranked lists with
        weighted Reciprocal Rank Fusion (RRF). Lexical/full-text channels are
        skipped for queries that are too short to benefit (guard against trigram
        index degradation). Any single-channel failure degrades to the remaining
        channels; if all derive channels fail, vector-only results are returned.
        """
        # Clean + length-guard the query for the derive (lexical/fulltext) channels
        cleaned = self._clean_query(question)
        derive_enabled = (
            settings.hybrid_search_enabled
            and len(cleaned) >= settings.hybrid_min_query_length
        )

        vector_chunks = await self._retrieve_vector_chunks(db, kb_id, query_embedding)
        if not derive_enabled:
            return vector_chunks[: settings.similarity_top_k]

        # Parallel: derivative channels both need the cleaned query.
        async def _lex() -> list[RetrievedChunk]:
            return await self._retrieve_lexical_chunks(db, kb_id, cleaned)

        async def _fulltext() -> list[RetrievedChunk]:
            return await self._retrieve_fulltext_chunks(db, kb_id, cleaned)

        lexical_chunks, fulltext_chunks = await asyncio.gather(_lex(), _fulltext())

        return self._rrf_fuse(
            {
                "vector": vector_chunks,
                "lexical": lexical_chunks,
                "fulltext": fulltext_chunks,
            },
            settings.rrf_top_k,
        )

    def _clean_query(self, query: str) -> str:
        """Normalize a query for trigram/full-text matching.

        Collapses full-width spaces and strips *trailing* punctuation/symbols
        that are unlikely to be part of meaningful search terms.  Word-internal
        punctuation (e.g. hyphens, dots) is preserved so that trigram matching
        can still locate substrings like "Python" in "What is Python?".
        """
        clean = re.sub(r"[\s\u3000]+", " ", query).strip()
        # Remove trailing punctuation/symbols only (not word boundaries).
        # Covers ASCII and full-width CJK punctuation; word-internal punctuation
        # (e.g. hyphens, dots) is preserved so trigram matching can still locate
        # substrings like "Python" in "What is Python?".
        clean = re.sub(
            "[\"'\u201c\u201d\u2018\u2019\u3001\u3002\uff0c\uff0e\uff1a\uff1b\uff1f\uff01\u00b7\u2026,;.?!:;!?@#$%^&*()_+=\\[\\]{}<>《》【】]+$",
            "",
            clean,
        )
        return clean if clean else query

    async def _retrieve_lexical_chunks(
        self,
        db: AsyncSession,
        kb_id: UUID,
        query: str,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks by trigram word-match similarity (pg_trgm).

        Uses ``word_similarity(query, text)`` rather than ``similarity(query, text)``.
        两者分母不同，量级差一个数量级以上（2026-09-10 实测）：

        - ``similarity(a, b) = |A∩B| / |A∪B|``：分母是 trigram 并集。短 query × 长
          chunk 时分母被 chunk 撑大，分数必然趋 0 —— 实测"剧本大纲"对命中段落只有
          **0.0118**，任何合理阈值都过不了，词法通道等于废的。
        - ``word_similarity(a, b)``：分母是 query 的 trigram 数，衡量"query 的
          trigram 在 text 中连续区间的最大覆盖率"。同一个例子实测 **1.0000**。

        行为上这恰好是混合检索想要的：关键词/实体型 query 能命中词法通道，
        自然语言长问句因无字面重叠而不命中，交给向量通道兜底。

        注意：函数写法无法命中 ``gin_trgm_ops`` 索引（索引只服务 ``<%``/``%>`` 算子），
        当前按 KB 分表、单表规模小，先用正确性优先；表变大后可改为
        ``WHERE :q <% text`` 并设置 ``pg_trgm.word_similarity_threshold``。

        Gracefully returns an empty list if the operator/extension is missing.
        """
        table_name = self._vector_index.table_name_from_str(str(kb_id))

        try:
            sql = f"""
                SELECT chunk_id, doc_id, text, metadata,
                       word_similarity(:q, text) AS sim
                FROM {table_name}
                WHERE word_similarity(:q, text) > :threshold
                ORDER BY sim DESC
                LIMIT :limit
            """
            result = await db.execute(
                sa_text(sql),
                {
                    "q": query,
                    "threshold": settings.trgm_similarity_threshold,
                    "limit": settings.lexical_top_k,
                },
            )
        except (OperationalError, ProgrammingError) as e:
            logger.warning("lexical_retrieval_failed", error=str(e))
            return []

        return self._rows_to_chunks(result.fetchall(), channel="lexical")

    # 中文停用字：这类字几乎出现在每个 chunk 里，用 OR 连接时会污染 ts_rank 排序，
    # 所以从全文查询里剔除。只剔除"功能字"，不动"人/大/中"这类可能承载语义的字。
    _FULLTEXT_STOPCHARS = frozenset(
        "的了吗呢吧啊是在有就都也还很太又再只把被给对从向并且而且但是因为所以"
        "我你他她它们这那么什么怎如何可以请帮下一些个之与及或者如果没不"
    )

    @classmethod
    def _cjk_or_tsquery(cls, query: str) -> str:
        """把中文查询转成 ``to_tsquery('simple', ...)`` 能吃的单字 OR 表达式。

        PG 的 ``simple`` 配置不做中文分词，整句中文会被当成一个大 token，导致
        ``tsvector @@ query`` 永远为 false（实测连"聊斋 剧本 大纲"都 0 命中）。
        索引侧（``rag_cjk_tsv``）已改为**逐字切分**，查询侧必须同粒度：把每个汉字
        拆出来，用 ``|``（OR）连接，让 ts_rank 按命中字数排序。

        用 OR 而非 AND 是刻意的：混合检索的价值在"召回互补"，精选交给 RRF 与重排；
        AND 会让"陈默推开木门"这类缺字的查询直接 0 命中。

        返回空字符串表示没有可用检索词，调用方应跳过该通道。
        """
        terms: list[str] = []
        buf: list[str] = []

        def _flush_word() -> None:
            """收尾一个拉丁词；单个孤立字母没有检索价值，丢弃。"""
            if buf:
                word = "".join(buf)
                if len(word) > 1:
                    terms.append(word)
                buf.clear()

        for ch in query:
            # 汉字 / 假名逐字入列（扩展 A 区、统一表意、假名、兼容表意）
            if (
                "\u3400" <= ch <= "\u4dbf"
                or "\u4e00" <= ch <= "\u9fff"
                or "\u3040" <= ch <= "\u30ff"
                or "\uf900" <= ch <= "\ufaff"
            ):
                _flush_word()
                if ch not in cls._FULLTEXT_STOPCHARS:
                    terms.append(ch)
            elif ch.isascii() and (ch.isalnum() or ch == "_"):
                buf.append(ch)
            else:
                # 标点/空白/全角符号：既不入检索词，也作为拉丁词的分隔符
                _flush_word()
        _flush_word()

        # 去重（保持顺序），避免同一个字在 OR 表达式里重复出现
        seen: set[str] = set()
        unique = [t for t in terms if not (t in seen or seen.add(t))]
        return " | ".join(unique)

    async def _retrieve_fulltext_chunks(
        self,
        db: AsyncSession,
        kb_id: UUID,
        query: str,
    ) -> list[RetrievedChunk]:
        """Retrieve chunks by PostgreSQL tsvector full-text ranking.

        索引侧是逐字切分的 ``tsv``（见 ``index_manager.rag_cjk_tsv``），所以查询侧
        也必须用逐字 OR 表达式，否则两边粒度不一致会永远匹配不上。
        Gracefully returns an empty list if the tsvector channel is unavailable.
        """
        table_name = self._vector_index.table_name_from_str(str(kb_id))

        tsquery = self._cjk_or_tsquery(query)
        if not tsquery:
            return []

        try:
            sql = f"""
                SELECT chunk_id, doc_id, text, metadata,
                       ts_rank(tsv, to_tsquery('simple', :q)) AS score
                FROM {table_name}
                WHERE tsv @@ to_tsquery('simple', :q)
                ORDER BY score DESC
                LIMIT :limit
            """
            result = await db.execute(
                sa_text(sql),
                {
                    "q": tsquery,
                    "limit": settings.fulltext_top_k,
                },
            )
        except (OperationalError, ProgrammingError) as e:
            logger.warning("fulltext_retrieval_failed", error=str(e))
            return []

        return self._rows_to_chunks(result.fetchall(), channel="fulltext")

    def _rows_to_chunks(
        self, rows, channel: str
    ) -> list[RetrievedChunk]:
        """Convert raw DB rows (chunk_id, doc_id, text, metadata, score) to chunks."""
        chunks: list[RetrievedChunk] = []
        for row in rows:
            chunk_id, doc_id, text, metadata, score = row
            meta = metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
            chunks.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    doc_id=str(doc_id),
                    text=text,
                    metadata=meta,
                    score=float(score),
                    # 单通道结果先原样带上；若随后进入 RRF 融合会被覆盖成融合原始分，
                    # 若走纯向量路径则保留余弦相似度，语义一致且可解释。
                    fused_score=float(score),
                    source=meta.get("filename", meta.get("source", "")),
                    channels=[channel],
                )
            )
        return chunks

    def _rrf_fuse(
        self,
        channels: dict[str, list[RetrievedChunk]],
        top_n: int,
    ) -> list[RetrievedChunk]:
        """Fuse ranked chunk lists using weighted Reciprocal Rank Fusion.

        Accumulates ``w_i / (k + rank)`` across channels, orders by the fused
        score, then normalizes to [0, 1] so downstream confidence gating keeps a
        stable scale even when the BGE reranker is disabled. Each result carries
        the merged set of channels that matched it.
        """
        import copy

        combined: dict[str, float] = {}
        payload: dict[str, RetrievedChunk] = {}
        matched: dict[str, set[str]] = {}
        k = settings.rrf_k

        weights: dict[str, float] = {
            "vector": settings.vector_weight,
            "lexical": settings.lexical_weight,
            "fulltext": settings.fulltext_weight,
        }

        for channel, chunks in channels.items():
            weight = weights.get(channel, 1.0)
            for rank, chunk in enumerate(chunks):
                cid = chunk.chunk_id
                combined[cid] = combined.get(cid, 0.0) + weight / (k + rank + 1)
                payload.setdefault(cid, chunk)
                matched.setdefault(cid, set()).add(channel)

        if not combined:
            return []

        # Order by fused score, then normalize to [0, 1] (max = 1.0).
        # 归一化值只用于排序/展示：它会让 top1 恒等于 1.0，丢失"召回质量"信息，
        # 因此原始 RRF 分同时保留在 ``fused_score`` 上供下游判别（见 RetrievedChunk）。
        ordered_ids = sorted(combined, key=lambda cid: combined[cid], reverse=True)[:top_n]
        max_score = combined[ordered_ids[0]] if ordered_ids else 1.0
        fused: list[RetrievedChunk] = []
        for cid in ordered_ids:
            chunk = copy.copy(payload[cid])
            chunk.fused_score = combined[cid]
            chunk.score = combined[cid] / max_score if max_score else 0.0
            ranked = sorted(matched.get(cid, []))
            chunk.channels = ranked or chunk.channels
            fused.append(chunk)
        return fused

    async def _retrieve_vector_chunks(
        self,
        db: AsyncSession,
        kb_id: UUID,
        query_embedding: list[float],
    ) -> list[RetrievedChunk]:
        """Retrieve relevant chunks using vector similarity search."""
        table_name = self._vector_index.table_name_from_str(str(kb_id))

        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

        sql = f"""
            SELECT chunk_id, doc_id, text, metadata,
                   1 - (embedding <=> CAST(:embedding AS vector)) as score
            FROM {table_name}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """

        result = await db.execute(
            sa_text(sql),
            {
                "embedding": embedding_str,
                "limit": settings.similarity_top_k,
            },
        )

        return self._rows_to_chunks(result.fetchall(), channel="vector")

    async def _rerank_chunks(
        self, question: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        """Rerank chunks using the local BGE cross-encoder reranker.

        Runs the synchronous reranker in a thread to avoid blocking the event
        loop. If the reranker is not available (missing model / inference error)
        or disabled, falls back to ordering by the initial similarity score.

        注意分数口径：重排后 ``score`` 是 **[0,1] 的 sigmoid 绝对值**，与
        ``_rrf_fuse`` 里 max 归一化后恒为 1.0 的 score 完全不是一回事，不可混用。
        原始 logit 保留在 ``reranker_logit``；未归一化的 RRF 融合分保留在
        ``fused_score``。拒答判据只用"召回是否为空"，不再依赖绝对分数
        （详见 config.py 中 ``confidence_gate_enabled`` 的说明）。
        """
        from app.core.reranker import rerank

        candidates = [
            {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "text": c.text,
             "metadata": c.metadata, "score": c.score, "source": c.source,
             "channels": c.channels, "fused_score": c.fused_score}
            for c in chunks
        ]

        if not candidates:
            return []

        reranked = await asyncio.to_thread(
            rerank, question, candidates, settings.rerank_top_n
        )

        results: list[RetrievedChunk] = []
        for c in reranked:
            # 原始 logit 必须留下来：sigmoid 之后的分数会掩盖"模型究竟觉得多相关"，
            # 排查检索质量/调阈值时这个值比 sigmoid 有用得多。
            logit = c.get("reranker_score")
            meta = dict(c.get("metadata") or {})
            if logit is not None:
                meta["reranker_score"] = float(logit)
            results.append(
                RetrievedChunk(
                    chunk_id=c["chunk_id"],
                    doc_id=c["doc_id"],
                    text=c["text"],
                    metadata=meta,
                    score=float(c["score"]),
                    fused_score=float(c.get("fused_score", c.get("score", 0.0))),
                    reranker_logit=float(logit) if logit is not None else None,
                    source=c.get("source", ""),
                    channels=list(c.get("channels", [])),
                )
            )
        return results

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        """Build context string from retrieved chunks, truncated to token budget."""
        llm = get_llm_provider()
        budget = settings.context_max_tokens

        parts = []
        used = 0
        for i, chunk in enumerate(chunks, 1):
            source = chunk.source or f"Document {chunk.doc_id[:8]}"
            block = f"[来源{i}: {source}]\n{chunk.text}"
            block_tokens = llm.count_tokens(block)
            if used + block_tokens > budget and parts:
                # Stop adding more chunks; at least one chunk is always included.
                break
            parts.append(block)
            used += block_tokens

        return "\n---\n".join(parts)

    def _build_messages(
        self,
        question: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """Build the messages list for the LLM chat completion.

        Returns [system, ...history, user_with_context] ready for the LLM.
        History is trimmed to fit within the model's context window budget.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        if history:
            history = self._trim_history(history, context, question)
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"上下文信息：\n{context}\n\n用户问题：{question}",
        })
        return messages

    def _trim_history(
        self,
        history: list[dict[str, str]],
        context: str,
        question: str,
    ) -> list[dict[str, str]]:
        """Trim history to fit within the model's context window budget.

        Budget = model_max_context - llm_max_tokens - 200 (buffer).
        Removes oldest (user, assistant) pairs until the total fits.
        Always keeps at least 1 round (2 messages) if budget allows.
        """
        llm = get_llm_provider()
        budget = settings.model_max_context - settings.llm_max_tokens - 200

        # Count fixed tokens: system prompt + context + question
        system_tokens = llm.count_tokens(self._system_prompt)
        context_tokens = llm.count_tokens(context)
        question_tokens = llm.count_tokens(question)
        fixed = system_tokens + context_tokens + question_tokens

        if fixed >= budget:
            # Context alone exceeds budget — keep history empty, let the LLM handle it
            logger.warning(
                "token_budget_exceeded",
                fixed_tokens=fixed,
                budget=budget,
                message="System+context already exceeds budget, dropping all history",
            )
            return []

        available = budget - fixed
        if not history:
            return []

        # Count total history tokens
        history_tokens = sum(llm.count_tokens(m["content"]) for m in history)
        if history_tokens <= available:
            return history

        # Trim oldest pairs (user+assistant) from the front
        trimmed: list[dict[str, str]] = []
        remaining = available
        # Process in reverse so we keep the most recent messages
        i = len(history) - 1
        while i >= 0:
            # Each turn is a pair: user then assistant
            # We trim complete pairs only, starting from the most recent
            if i >= 1 and history[i - 1]["role"] == "user" and history[i]["role"] == "assistant":
                pair_tokens = llm.count_tokens(history[i - 1]["content"]) + llm.count_tokens(
                    history[i]["content"]
                )
                if pair_tokens <= remaining:
                    trimmed.insert(0, history[i])        # assistant
                    trimmed.insert(0, history[i - 1])    # user
                    remaining -= pair_tokens
                    i -= 2
                    continue
                elif not trimmed:
                    # Even the most recent pair doesn't fit — keep one message as fallback
                    single = history[i]["content"]
                    single_tokens = llm.count_tokens(single)
                    if single_tokens <= available:
                        trimmed.insert(0, history[i])
                        if i >= 1:
                            trimmed.insert(0, history[i - 1])
                    break
                else:
                    break
            i -= 1

        if len(trimmed) < len(history):
            logger.info(
                "history_trimmed",
                original_rounds=len(history) // 2,
                kept_rounds=len(trimmed) // 2,
                budget=budget,
                used=available - remaining,
            )

        return trimmed

    async def _generate(
        self, question: str, context: str, history: list[dict[str, str]] | None = None
    ) -> tuple[str, int]:
        """Generate answer using LLM."""
        messages = self._build_messages(question, context, history)

        # Run in thread if provider is sync
        llm = get_llm_provider()
        answer, tokens = await llm.chat(messages, max_tokens=settings.llm_max_tokens)
        return answer, tokens

    async def _generate_stream(
        self,
        question: str,
        context: str,
        sources: list[RetrievedChunk],
        start_time: float,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Generate answer as a stream.

        Yields JSON strings with:
        - type: "content" | "sources" | "done" | "error"
        """
        messages = self._build_messages(question, context, history)

        # First, send sources
        sources_data = [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "source": c.source,
                "score": c.score,
                "text_preview": c.text[:200],
                "channels": list(c.channels),
            }
            for c in sources
        ]
        yield json.dumps({"type": "sources", "data": sources_data}, ensure_ascii=False)

        # Then stream content
        llm = get_llm_provider()
        full_answer = ""
        try:
            async for chunk in llm.chat_stream(messages, max_tokens=settings.llm_max_tokens):
                full_answer += chunk
                yield json.dumps({"type": "content", "data": chunk}, ensure_ascii=False)
        except Exception as e:
            logger.error("llm_stream_error", error=str(e))
            yield json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False)
            return

        latency_ms = int((time.time() - start_time) * 1000)
        yield json.dumps(
            {
                "type": "done",
                "data": {
                    "latency_ms": latency_ms,
                    "tokens_used": llm.count_tokens(full_answer),
                    "confidence": sources[0].score if sources else 0,
                },
            },
            ensure_ascii=False,
        )

    async def _generate_refusal_stream(
        self, answer: str, start_time: float
    ) -> AsyncGenerator[str, None]:
        """Streaming refusal path.

        When the confidence check fails, query(stream=True) must still return an
        async generator (matching the contract ChatService._chat_stream expects),
        otherwise it receives a RAGResponse and `async for chunk in stream_gen`
        raises AssertionError. Emits the same JSON envelope as _generate_stream.
        """
        # No sources for a refusal -> downstream marks it as refused automatically.
        yield json.dumps({"type": "sources", "data": []}, ensure_ascii=False)

        # Stream the refusal text as a single content chunk.
        yield json.dumps({"type": "content", "data": answer}, ensure_ascii=False)

        latency_ms = int((time.time() - start_time) * 1000)
        # Pre-compute static refusal token count (lazily, once)
        if RAGEngine._refusal_tokens is None:
            llm = get_llm_provider()
            RAGEngine._refusal_tokens = llm.count_tokens(answer) if llm else len(answer) // 2
        yield json.dumps(
            {
                "type": "done",
                "data": {
                    "latency_ms": latency_ms,
                    "tokens_used": RAGEngine._refusal_tokens,
                    "confidence": 0,
                },
            },
            ensure_ascii=False,
        )

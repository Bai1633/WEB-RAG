"""Tests for RAG engine core logic."""

from unittest.mock import patch

from app.core.rag_engine import RAGEngine, RAGResponse, RetrievedChunk


class TestRetrievedChunk:
    def test_default_values(self):
        chunk = RetrievedChunk(chunk_id="1", doc_id="d1", text="hello")
        assert chunk.chunk_id == "1"
        assert chunk.doc_id == "d1"
        assert chunk.text == "hello"
        assert chunk.score == 0.0
        assert chunk.source == ""
        assert chunk.channels == []
        assert chunk.metadata == {}

    def test_with_channels(self):
        chunk = RetrievedChunk(
            chunk_id="1", doc_id="d1", text="hello", channels=["vector", "lexical"]
        )
        assert chunk.channels == ["vector", "lexical"]


class TestRAGResponse:
    def test_default_refused(self):
        resp = RAGResponse(answer="test", sources=[], confidence=0.0, tokens_used=0, latency_ms=100)
        assert resp.refused is False
        assert resp.refusal_reason == ""

    def test_refused_response(self):
        resp = RAGResponse(
            answer="I cannot answer.",
            sources=[],
            confidence=0.0,
            tokens_used=0,
            latency_ms=50,
            refused=True,
            refusal_reason="below_confidence_threshold",
        )
        assert resp.refused is True
        assert resp.refusal_reason == "below_confidence_threshold"


class TestRAGEngineInit:
    def test_default_system_prompt(self):
        engine = RAGEngine()
        assert "专业的知识库问答助手" in engine._system_prompt

    def test_custom_system_prompt(self, monkeypatch):
        # Patch the cached settings singleton directly: setting the env var
        # would have no effect because get_settings() is lru_cached.
        from app.config import get_settings

        monkeypatch.setattr(
            get_settings(), "system_prompt", "You are a helpful assistant."
        )
        engine = RAGEngine()
        assert engine._system_prompt == "You are a helpful assistant."


class TestBuildContext:
    def test_builds_context_from_chunks(self):
        engine = RAGEngine()
        chunks = [
            RetrievedChunk(chunk_id="1", doc_id="d1", text="text1", source="doc.pdf"),
            RetrievedChunk(chunk_id="2", doc_id="d2", text="text2", source="doc2.pdf"),
        ]
        context = engine._build_context(chunks)
        assert "[来源1: doc.pdf]" in context
        assert "text1" in context
        assert "[来源2: doc2.pdf]" in context
        assert "text2" in context

    def test_fallback_source_when_empty(self):
        engine = RAGEngine()
        chunks = [
            RetrievedChunk(chunk_id="1", doc_id="abcdef1234567890", text="text1", source=""),
        ]
        context = engine._build_context(chunks)
        assert "abcdef12" in context or "text1" in context


class TestCleanQuery:
    def test_collapses_whitespace(self):
        engine = RAGEngine()
        # Inner whitespace collapses to single spaces but is kept: the
        # tsvector channel relies on word boundaries for English queries.
        result = engine._clean_query("   hello world   ")
        assert result == "hello world"

    def test_removes_punctuation_chinese(self):
        engine = RAGEngine()
        result = engine._clean_query("什么是Python？")
        assert result == "什么是Python"

    def test_removes_punctuation_english(self):
        engine = RAGEngine()
        result = engine._clean_query("What is Python?!")
        assert result == "What is Python"

    def test_short_query(self):
        engine = RAGEngine()
        result = engine._clean_query("a")
        assert len(result) <= 1


class TestRRFFuse:
    def test_single_channel(self):
        engine = RAGEngine()
        chunks = [
            RetrievedChunk(chunk_id="1", doc_id="d1", text="t1", score=0.9, channels=["vector"]),
        ]
        result = engine._rrf_fuse({"vector": chunks}, top_n=5)
        assert len(result) == 1
        assert result[0].score == 1.0

    def test_dual_channel_merge(self):
        engine = RAGEngine()
        vector = [
            RetrievedChunk(chunk_id="1", doc_id="d1", text="t1", score=0.9, channels=["vector"]),
        ]
        lexical = [
            RetrievedChunk(chunk_id="1", doc_id="d1", text="t1", score=0.8, channels=["lexical"]),
        ]
        result = engine._rrf_fuse({"vector": vector, "lexical": lexical}, top_n=5)
        assert len(result) == 1
        assert set(result[0].channels) == {"lexical", "vector"}

    def test_empty_input(self):
        engine = RAGEngine()
        result = engine._rrf_fuse({}, top_n=5)
        assert result == []

    def test_respects_top_n(self):
        engine = RAGEngine()
        chunks = [
            RetrievedChunk(chunk_id=str(i), doc_id="d", text="t", score=1.0, channels=["vector"])
            for i in range(10)
        ]
        result = engine._rrf_fuse({"vector": chunks}, top_n=3)
        assert len(result) == 3

class _FakeLLM:
    """Minimal LLM stub: replies with a canned string or raises."""

    def __init__(self, reply):
        self.reply = reply
        self.calls: list = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, 10


class TestRewriteQuery:
    """Multi-turn query rewriting (condense follow-up into standalone query)."""

    def _history(self):
        return [
            {"role": "user", "content": "Web RAG 项目用了什么向量数据库？"},
            {"role": "assistant", "content": "项目使用 PostgreSQL + pgvector 存储向量。"},
        ]

    def test_rewrites_followup_with_history(self, monkeypatch):

        import asyncio

        fake = _FakeLLM("pgvector 支持哪些索引类型？")
        engine = RAGEngine()
        with patch("app.core.rag_engine.get_llm_provider", return_value=fake):
            result = asyncio.run(engine._rewrite_query("它支持哪些索引？", self._history()))
        assert result == "pgvector 支持哪些索引类型？"
        # The rewrite prompt must include the history content
        sent = fake.calls[0]
        assert "pgvector 存储向量" in sent[1]["content"]

    def test_strips_quotes_and_takes_first_line(self):

        import asyncio

        fake = _FakeLLM('"pgvector 的索引类型"\n多余的一行')
        engine = RAGEngine()
        with patch("app.core.rag_engine.get_llm_provider", return_value=fake):
            result = asyncio.run(engine._rewrite_query("它有哪些索引？", self._history()))
        assert result == "pgvector 的索引类型"

    def test_falls_back_on_llm_error(self):

        import asyncio

        fake = _FakeLLM(RuntimeError("api down"))
        engine = RAGEngine()
        with patch("app.core.rag_engine.get_llm_provider", return_value=fake):
            result = asyncio.run(engine._rewrite_query("它有哪些索引？", self._history()))
        assert result == "它有哪些索引？"

    def test_falls_back_on_empty_output(self):

        import asyncio

        fake = _FakeLLM("   ")
        engine = RAGEngine()
        with patch("app.core.rag_engine.get_llm_provider", return_value=fake):
            result = asyncio.run(engine._rewrite_query("它有哪些索引？", self._history()))
        assert result == "它有哪些索引？"

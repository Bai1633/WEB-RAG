"""Tests for the mock embedding provider (deterministic, offline)."""

import pytest

from app.core.embedding import MockEmbeddingProvider, get_embedding_provider


class TestMockEmbeddingProvider:
    def test_deterministic_and_dimension(self):
        p = MockEmbeddingProvider(dim=128)
        v1 = p.get_embeddings(["向量检索 pipeline"])[0]
        v2 = p.get_embeddings(["向量检索 pipeline"])[0]
        assert v1 == v2
        assert len(v1) == 128
        assert p.dimension == 128

    def test_unit_normalized(self):
        p = MockEmbeddingProvider(dim=64)
        v = p.get_embeddings(["hello world"])[0]
        assert abs(sum(x * x for x in v) - 1.0) < 1e-9

    def test_shared_tokens_score_higher(self):
        p = MockEmbeddingProvider(dim=256)
        q = p.get_embeddings(["HNSW 索引参数"])[0]
        near = p.get_embeddings(["HNSW 索引的构建参数有哪些？"])[0]
        far = p.get_embeddings(["今天天气怎么样"])[0]

        def dot(a, b):
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert dot(q, near) > dot(q, far)

    def test_rejects_tiny_dim(self):
        with pytest.raises(ValueError):
            MockEmbeddingProvider(dim=8)

    def test_config_branch(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "embedding_provider", "mock")
        monkeypatch.setattr(get_settings(), "embedding_dim", 128)
        get_embedding_provider.cache_clear()
        try:
            provider = get_embedding_provider()
            assert isinstance(provider, MockEmbeddingProvider)
            assert provider.dimension == 128
        finally:
            get_embedding_provider.cache_clear()

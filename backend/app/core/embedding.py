"""Embedding provider abstraction with singleton caching.

Supports: OpenAI, HuggingFace (local), Ollama
All providers are cached as singletons to avoid per-request reconstruction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from functools import lru_cache

from app.config import get_settings

try:
    from llama_index.embeddings.openai import OpenAIEmbedding
except ImportError:  # pragma: no cover - embedding extra optional
    OpenAIEmbedding = None  # type: ignore[assignment]

try:
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding
except ImportError:  # pragma: no cover - embedding extra optional
    OpenAILikeEmbedding = None  # type: ignore[assignment]

settings = get_settings()
logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimension of the embedding vectors."""
        ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI API embedding provider."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        batch_size: int = 32,
    ) -> None:
        from llama_index.embeddings.openai_like import OpenAILikeEmbedding

        if OpenAILikeEmbedding is None:
            raise ImportError(
                "OpenAI-compatible embedding requires "
                "llama-index-embeddings-openai-like"
            )

        self._model_name = model_name
        self._batch_size = batch_size
        # OpenAILikeEmbedding is the officially supported class for any
        # OpenAI-compatible endpoint (DashScope/Qwen, vLLM, Ollama, ...).
        # Unlike OpenAIEmbedding it does NOT validate the model name against
        # OpenAI's enum, so custom model names such as Qwen embeddings work
        # out of the box without relying on private attributes.
        # Pass ``dimensions`` explicitly so the API returns exactly
        # EMBEDDING_DIM, matching the pgvector column created in
        # db/vector_store.py (qwen3.7-text-embedding supports 256~2560).
        self._embed_model = OpenAILikeEmbedding(
            model_name=model_name,
            api_key=api_key,
            api_base=base_url,
            dimensions=settings.embedding_dim,
        )
        self._dimension: int | None = None

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_embeddings = self._embed_model.get_text_embedding_batch(batch)
            if isinstance(batch_embeddings, list) and batch_embeddings and isinstance(batch_embeddings[0], list):
                embeddings.extend(batch_embeddings)
            else:
                embeddings.append(batch_embeddings)  # type: ignore
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            test_emb = self._embed_model.get_text_embedding("test")
            self._dimension = len(test_emb)
        return self._dimension


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Local HuggingFace embedding provider using sentence-transformers."""

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        self._model_name = model_name
        self._batch_size = batch_size
        self._embed_model = HuggingFaceEmbedding(model_name=model_name)
        self._dimension: int | None = None

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_embeddings = self._embed_model.get_text_embedding_batch(batch)
            if isinstance(batch_embeddings, list) and batch_embeddings and isinstance(batch_embeddings[0], list):
                embeddings.extend(batch_embeddings)
            else:
                embeddings.append(batch_embeddings)  # type: ignore
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            test_emb = self._embed_model.get_text_embedding("test")
            self._dimension = len(test_emb)
        return self._dimension


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama embedding provider."""

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:11434",
        batch_size: int = 32,
    ) -> None:
        try:
            from llama_index.embeddings.ollama import OllamaEmbedding
        except ImportError as e:
            raise ImportError(
                "Ollama embedding provider requires llama-index-embeddings-ollama"
            ) from e

        self._model_name = model_name
        self._batch_size = batch_size
        self._embed_model = OllamaEmbedding(
            model_name=model_name,
            base_url=base_url,
        )
        self._dimension: int | None = None

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_embeddings = self._embed_model.get_text_embedding_batch(batch)
            if isinstance(batch_embeddings, list) and batch_embeddings and isinstance(batch_embeddings[0], list):
                embeddings.extend(batch_embeddings)
            else:
                embeddings.append(batch_embeddings)  # type: ignore
        return embeddings

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            test_emb = self._embed_model.get_text_embedding("test")
            self._dimension = len(test_emb)
        return self._dimension


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Get the configured embedding provider (singleton)."""
    provider = settings.embedding_provider.lower()

    if provider == "openai":
        if not settings.embedding_api_key:
            logger.warning("OpenAI API key not set, embeddings may fail")
        return OpenAIEmbeddingProvider(
            model_name=settings.embedding_model_name,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            batch_size=settings.embedding_batch_size,
        )
    elif provider in ("huggingface", "hf", "local"):
        return HuggingFaceEmbeddingProvider(
            model_name=settings.embedding_model_name,
            batch_size=settings.embedding_batch_size,
        )
    elif provider == "ollama":
        return OllamaEmbeddingProvider(
            model_name=settings.embedding_model_name,
            base_url=settings.embedding_base_url,
            batch_size=settings.embedding_batch_size,
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

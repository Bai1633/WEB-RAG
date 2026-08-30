"""LLM provider abstraction with singleton caching.

Supports: OpenAI, Ollama, Compatible (OpenAI-compatible)
All providers are cached as singletons to avoid per-request reconstruction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, int]:
        """Chat completion - non-streaming.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            **kwargs: Additional provider-specific arguments.

        Returns:
            Tuple of (response_text, total_tokens_used).
        """
        ...

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Chat completion - streaming.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            **kwargs: Additional provider-specific arguments.

        Yields:
            Chunks of response text.
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string using the provider's tokenizer."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the model."""
        ...


class OpenAILLMProvider(LLMProvider):
    """OpenAI API LLM provider."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> None:
        from openai import AsyncOpenAI

        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, int]:
        temperature = kwargs.get("temperature", self._temperature)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        response = await self._client.chat.completions.create(
            model=self._model_name,
            messages=messages,  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else self.count_tokens(text)
        return text, tokens

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        temperature = kwargs.get("temperature", self._temperature)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        stream = await self._client.chat.completions.create(
            model=self._model_name,
            messages=messages,  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @property
    def model_name(self) -> str:
        return self._model_name

    def count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken (cl100k_base for OpenAI-compatible models)."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            # Fallback: rough estimate (4 chars per token for English, ~1.5 for Chinese)
            return len(text) // 2


class OllamaLLMProvider(LLMProvider):
    """Ollama LLM provider."""

    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> None:
        try:
            import ollama
        except ImportError as e:
            raise ImportError("Ollama provider requires the 'ollama' package") from e

        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._base_url = base_url
        self._client = ollama.AsyncClient(host=base_url)

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, int]:
        temperature = kwargs.get("temperature", self._temperature)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        response = await self._client.chat(
            model=self._model_name,
            messages=messages,
            options={"temperature": temperature, "num_predict": max_tokens},
            stream=False,
        )
        text = response.get("message", {}).get("content", "")
        tokens = self.count_tokens(text)
        return text, tokens

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        temperature = kwargs.get("temperature", self._temperature)
        max_tokens = kwargs.get("max_tokens", self._max_tokens)

        stream = await self._client.chat(
            model=self._model_name,
            messages=messages,
            options={"temperature": temperature, "num_predict": max_tokens},
            stream=True,
        )
        async for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    @property
    def model_name(self) -> str:
        return self._model_name

    def count_tokens(self, text: str) -> int:
        """Ollama doesn't expose token counts. Use tiktoken as approximation."""
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 2


class CompatibleLLMProvider(OpenAILLMProvider):
    """OpenAI-compatible API provider (same as OpenAI, just different default base URL)."""

    pass


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Get the configured LLM provider (singleton)."""
    provider = settings.llm_provider.lower()

    if provider in ("openai", "compatible"):
        if not settings.llm_api_key:
            logger.warning("LLM API key not set, chat may fail")
        return OpenAILLMProvider(
            model_name=settings.llm_model_name,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    elif provider == "ollama":
        return OllamaLLMProvider(
            model_name=settings.llm_model_name,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")

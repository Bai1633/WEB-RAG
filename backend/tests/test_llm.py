"""Tests for LLM provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import get_settings
from app.core.llm import OllamaLLMProvider, OpenAILLMProvider, get_llm_provider


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    """get_llm_provider is an lru_cache singleton; clear it so each test
    starts cold and the settings patch below is actually observed."""
    get_llm_provider.cache_clear()
    yield
    get_llm_provider.cache_clear()


class TestGetLLMProvider:
    def test_returns_singleton(self, monkeypatch):
        # Patch the cached settings singleton (get_llm_provider reads the
        # materialized settings object, not os.environ).
        s = get_settings()
        monkeypatch.setattr(s, "llm_provider", "openai")
        monkeypatch.setattr(s, "llm_api_key", "test-key")
        p1 = get_llm_provider()
        p2 = get_llm_provider()
        assert p1 is p2  # lru_cache singleton

    def test_unsupported_provider(self, monkeypatch):
        s = get_settings()
        monkeypatch.setattr(s, "llm_provider", "unsupported")
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_provider()


class TestOpenAILLMProvider:
    def test_model_name(self):
        provider = OpenAILLMProvider(
            model_name="gpt-4",
            api_key="test-key",
        )
        assert provider.model_name == "gpt-4"

    def test_count_tokens(self):
        provider = OpenAILLMProvider(
            model_name="gpt-4",
            api_key="test-key",
        )
        count = provider.count_tokens("Hello, world!")
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_chinese(self):
        provider = OpenAILLMProvider(
            model_name="gpt-4",
            api_key="test-key",
        )
        count = provider.count_tokens("你好世界")
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_empty(self):
        provider = OpenAILLMProvider(
            model_name="gpt-4",
            api_key="test-key",
        )
        count = provider.count_tokens("")
        assert count == 0

    @pytest.mark.asyncio
    async def test_chat_returns_tuple(self):
        provider = OpenAILLMProvider(
            model_name="gpt-4",
            api_key="test-key",
        )
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello!"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(total_tokens=10)
        # chat() awaits create(), so the mock itself must be awaitable
        with patch.object(
            provider._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response

            text, tokens = await provider.chat([{"role": "user", "content": "hi"}])
            assert text == "Hello!"
            assert tokens == 10


class TestOllamaLLMProvider:
    def test_count_tokens(self):
        provider = OllamaLLMProvider(
            model_name="llama3",
            base_url="http://localhost:11434",
        )
        count = provider.count_tokens("Hello, world!")
        assert count > 0
        assert isinstance(count, int)

    def test_model_name(self):
        provider = OllamaLLMProvider(
            model_name="llama3",
            base_url="http://localhost:11434",
        )
        assert provider.model_name == "llama3"

"""Tests for application configuration.

Settings are constructed directly with ``_env_file=None`` so tests assert
code defaults rather than whatever the developer's ``.env`` happens to
contain.  This also sidesteps the ``get_settings()`` lru_cache, which would
otherwise freeze the first instance across all tests and silently turn the
monkeypatch-based override tests into no-ops.
"""

from app.config import Settings


class TestSettings:
    def test_defaults(self):
        settings = Settings(_env_file=None)
        assert settings.llm_provider == "compatible"
        assert settings.llm_model_name == "qwen-turbo"
        assert settings.confidence_threshold == 0.35
        assert settings.rerank_top_n == 5
        assert settings.hybrid_search_enabled is True
        assert settings.chat_history_rounds == 5

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.5")
        monkeypatch.setenv("CHAT_HISTORY_ROUNDS", "10")
        monkeypatch.setenv("HYBRID_SEARCH_ENABLED", "false")
        settings = Settings(_env_file=None)
        assert settings.confidence_threshold == 0.5
        assert settings.chat_history_rounds == 10
        assert settings.hybrid_search_enabled is False

    def test_rrf_weights(self):
        settings = Settings(_env_file=None)
        assert settings.vector_weight == 1.0
        assert settings.lexical_weight == 1.0
        assert settings.fulltext_weight == 1.0

    def test_hybrid_min_query_length(self, monkeypatch):
        monkeypatch.setenv("HYBRID_MIN_QUERY_LENGTH", "5")
        settings = Settings(_env_file=None)
        assert settings.hybrid_min_query_length == 5

    def test_system_prompt(self, monkeypatch):
        monkeypatch.setenv("SYSTEM_PROMPT", "Custom prompt")
        settings = Settings(_env_file=None)
        assert settings.system_prompt == "Custom prompt"

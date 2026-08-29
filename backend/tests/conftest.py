"""Shared fixtures for pytest tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db_session():
    """Mock async SQLAlchemy session."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def sample_chunks():
    """Sample retrieved chunks for testing."""
    return [
        {
            "chunk_id": "chunk-1",
            "doc_id": "doc-1",
            "text": "Python is a programming language.",
            "metadata": {"filename": "python_intro.pdf"},
            "score": 0.95,
            "source": "python_intro.pdf",
        },
        {
            "chunk_id": "chunk-2",
            "doc_id": "doc-1",
            "text": "Python supports async programming.",
            "metadata": {"filename": "python_intro.pdf"},
            "score": 0.85,
            "source": "python_intro.pdf",
        },
        {
            "chunk_id": "chunk-3",
            "doc_id": "doc-2",
            "text": "FastAPI is a web framework.",
            "metadata": {"filename": "fastapi_doc.pdf"},
            "score": 0.60,
            "source": "fastapi_doc.pdf",
        },
    ]


@pytest.fixture
def sample_history():
    """Sample conversation history messages."""
    return [
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
    ]

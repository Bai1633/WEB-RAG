"""Unit tests for StatsService aggregation logic (DB mocked)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.stats_service import StatsService


def _make_service(status_rows, chunk_total, chat_row):
    """Build a StatsService whose session returns canned results in order."""
    session = AsyncMock()

    def execute_result(rows, scalar=None, one=None):
        result = MagicMock()
        result.all.return_value = rows
        result.scalar.return_value = scalar
        result.one.return_value = one
        return result

    responses = [
        execute_result(status_rows),            # documents group-by status
        execute_result([], scalar=chunk_total),  # sum(chunk_count)
        execute_result([], one=chat_row),        # count + sum(tokens)
    ]
    session.execute = AsyncMock(side_effect=responses)

    service = StatsService(session)
    kb = MagicMock()
    kb.id = uuid4()
    service.kb_repo.get_accessible_by_user = AsyncMock(return_value=[kb])
    return service


@pytest.mark.asyncio
async def test_aggregates_documents_and_chat():
    service = _make_service(
        status_rows=[("completed", 3), ("processing", 1), ("failed", 2)],
        chunk_total=120,
        chat_row=(7, 1530),
    )
    stats = await service.get_user_stats(uuid4())

    assert stats["knowledge_bases"] == 1
    assert stats["documents"] == {"total": 6, "completed": 3, "in_flight": 1, "failed": 2}
    assert stats["chunks"] == 120
    assert stats["chat_rounds"] == 7
    assert stats["total_tokens"] == 1530


@pytest.mark.asyncio
async def test_empty_kb_scope_returns_zeros():
    session = AsyncMock()
    service = StatsService(session)
    service.kb_repo.get_accessible_by_user = AsyncMock(return_value=[])

    stats = await service.get_user_stats(uuid4())

    assert stats == {
        "knowledge_bases": 0,
        "documents": {"total": 0, "completed": 0, "in_flight": 0, "failed": 0},
        "chunks": 0,
        "chat_rounds": 0,
        "total_tokens": 0,
    }
    # No queries are issued when the user has no accessible KBs
    session.execute.assert_not_called()

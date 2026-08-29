"""Unit tests for the pure retrieval-evaluation metrics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.compute_metrics import (  # noqa: E402
    hit_at_k,
    keyword_coverage,
    percentile,
    recall_at_k,
    reciprocal_rank,
)


class TestHitAtK:
    def test_hit_in_top_k(self):
        assert hit_at_k(["a", "b", "c"], {"b"}, k=2) is True

    def test_miss_beyond_k(self):
        assert hit_at_k(["a", "b", "c"], {"c"}, k=2) is False

    def test_k_zero_never_hits(self):
        assert hit_at_k(["a"], {"a"}, k=0) is False


class TestRecallAtK:
    def test_partial_recall(self):
        assert recall_at_k(["a", "x", "b"], {"a", "b", "c"}, k=3) == 2 / 3

    def test_dedupes_retrieved(self):
        # Same relevant doc retrieved twice must not inflate recall
        assert recall_at_k(["a", "a", "b"], {"a", "b"}, k=3) == 1.0

    def test_empty_relevant_is_zero(self):
        assert recall_at_k(["a"], set(), k=1) == 0.0


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank(["a", "b"], {"a"}) == 1.0

    def test_second_position(self):
        assert reciprocal_rank(["x", "a"], {"a"}) == 0.5

    def test_no_hit(self):
        assert reciprocal_rank(["x", "y"], {"a"}) == 0.0


class TestKeywordCoverage:
    def test_full_coverage(self):
        assert keyword_coverage(["HNSW uses ef_construction"], ["HNSW", "ef_construction"]) == 1.0

    def test_partial_coverage(self):
        assert keyword_coverage(["only this"], ["this", "missing"]) == 0.5

    def test_empty_keywords_is_zero(self):
        assert keyword_coverage(["text"], []) == 0.0


class TestPercentile:
    def test_nearest_rank(self):
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        assert percentile(values, 50) == 0.3
        assert percentile(values, 100) == 0.5
        assert percentile(values, 0) == 0.1

    def test_empty(self):
        assert percentile([], 50) == 0.0

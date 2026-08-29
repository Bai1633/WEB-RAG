"""Retrieval evaluation metrics — pure functions, no I/O, unit-testable.

Conventions:
- ``retrieved_ids``: ranked list of chunk identifiers (e.g. source filename),
    best first.
- ``relevant_ids``: the set of identifiers considered correct for the case.
"""

from __future__ import annotations


def hit_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> bool:
    """Whether any relevant chunk appears in the top-k results."""
    if k <= 0:
        return False
    return any(rid in relevant_ids for rid in retrieved_ids[:k])


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of relevant chunks covered by the top-k results.

    When multiple chunks map to the same relevant id (e.g. several chunks of
    one expected document), deduplicate retrieved ids before matching.
    """
    if not relevant_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    return len(top & relevant_ids) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """1 / rank of the first relevant result (0 when nothing relevant found)."""
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


def keyword_coverage(texts: list[str], keywords: list[str]) -> float:
    """Fraction of keywords present anywhere across the given chunk texts."""
    if not keywords:
        return 0.0
    joined = "\n".join(texts)
    found = sum(1 for kw in keywords if kw and kw in joined)
    return found / len(keywords)


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile of a list of floats (0 when empty)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]

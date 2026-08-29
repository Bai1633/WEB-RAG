"""BGE reranker - cross-encoder relevance reranking with local model.

Loads the local ``bge-reranker-v2-m3`` checkpoint (transformers format) once,
then scores ``(query, chunk)`` pairs and returns a reordered shortlist.

The model, tokenizer, and device are cached after the first successful load
(thread-safe via a module-level lock).  Subsequent calls reuse the loaded
artifacts so that ``from_pretrained`` is only called once.

Designed to be safe to run on CPU and to degrade gracefully: if the model
checkpoint is missing or inference fails, callers fall back to score ordering.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()
lib_logger = logging.getLogger("reranker")


class _BGERerankerCore:
    """Lazy handle around the transformers cross-encoder model.

    The model, tokenizer, and device are loaded once and cached in module-level
    globals protected by ``_model_lock``.  ``score_pairs`` is thus safe to call
    from multiple threads (e.g. via ``asyncio.to_thread``).
    """

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    def _ensure_loaded(self) -> None:
        """Load model & tokenizer if not already cached."""
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self._model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(self._model_path)
        self._model.eval()

        if torch.cuda.is_available():
            self._device = "cuda"
            self._model = self._model.to("cuda")

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Score ``(query, passage)`` pairs. Returns raw logits (higher = more relevant)."""
        import torch

        self._ensure_loaded()

        batched = [list(pair) for pair in pairs]
        with torch.no_grad():
            inputs = self._tokenizer(
                batched,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            if self._device == "cuda":
                inputs = {k: v.to(self._device) for k, v in inputs.items()}
            outputs = self._model(**inputs, return_dict=True)
            # Cross-encoder logits: [batch, num_labels], squeeze to (batch,)
            logits = outputs.logits.view(-1).float()
            return logits.tolist()


# --- Module-level singletons (thread-safe) ---

_reranker: _BGERerankerCore | None = None
_load_error: str | None = None
_model_lock = threading.Lock()


def _get_reranker() -> _BGERerankerCore | None:
    """Get the singleton reranker, or None (with _load_error set) if unavailable.

    Thread-safe: uses a lock to ensure the model is only loaded once even under
    concurrent ``asyncio.to_thread`` calls.
    """
    global _reranker, _load_error

    if _reranker is not None or _load_error is not None:
        return _reranker

    with _model_lock:
        # Double-check after acquiring the lock
        if _reranker is not None or _load_error is not None:
            return _reranker

        model_path = settings.rerank_model_path
        try:
            core = _BGERerankerCore(model_path)
            core._ensure_loaded()  # eager-load under lock for thread safety
            _reranker = core
            logger.info("reranker_loaded", model_path=model_path)
            return _reranker
        except Exception as e:  # pragma: no cover - depends on local model
            _load_error = str(e)
            lib_logger.warning(
                "reranker_load_failed", error=_load_error, model_path=model_path
            )
            return None


@lru_cache(maxsize=1)
def reranker_enabled() -> bool:
    """Whether heavyweight BGE reranking is requested by configuration."""
    return bool(settings.rerank_enabled)


def rerank(
    query: str,
    candidates: Sequence[dict[str, Any]],
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """Rerank candidate chunks by cross-encoder relevance.

    Args:
        query: The user question.
        candidates: List of dicts, each must contain at least ``text`` and
            ``score``. Other keys are preserved on the returned items.
        top_n: Number of chunks to keep. Defaults to ``settings.rerank_top_n``.

    Returns:
        Reordered candidate list capped at ``top_n`` with a new ``score`` (sigmoid)
        and ``reranker_score`` (raw logit).
    """
    keep = top_n or settings.rerank_top_n
    if not candidates:
        return []
    if not reranker_enabled():
        return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)[:keep]

    core = _get_reranker()
    if core is None:
        # Fallback: order by initial similarity score.
        return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)[:keep]

    pairs = [(query, c.get("text", "")) for c in candidates]
    try:
        logits = core.score_pairs(pairs)
    except Exception as e:  # pragma: no cover - runtime inference failure
        lib_logger.warning("reranker_inference_failed", error=str(e))
        return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)[:keep]

    def _sigmoid(x: float) -> float:
        """Map raw logit to a [0,1] relevance score."""
        if x >= 0:
            return 1.0 / (1.0 + math.exp(-x))
        exp = math.exp(x)
        return exp / (1.0 + exp)

    normalized = [
        {**c, "reranker_score": float(sc), "score": _sigmoid(float(sc))}
        for c, sc in zip(candidates, logits, strict=False)
    ]
    normalized.sort(key=lambda c: c["score"], reverse=True)
    return normalized[:keep]

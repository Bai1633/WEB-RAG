"""Text chunking strategies for RAG.

Implements semantic-aware chunking with overlap, preserving sentence boundaries.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A text chunk."""

    text: str
    index: int
    metadata: dict


class TextChunker:
    """Chunk text into segments with configurable size and overlap."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        """Split text into overlapping chunks.

        Strategy:
        1. Split text into sentences
        2. Group sentences into chunks of approximately chunk_size chars
        3. Overlap chunks by chunk_overlap chars

        Args:
            text: Input text.
            metadata: Base metadata to include in each chunk.

        Returns:
            List of Chunk objects.
        """
        if not text or not text.strip():
            return []

        base_metadata = metadata or {}
        sentences = self._split_sentences(text)

        if not sentences:
            return []

        chunks: list[Chunk] = []
        current_chunk: list[str] = []
        current_size = 0

        raw_chunks: list[list[str]] = []
        for sentence in sentences:
            sentence_len = len(sentence)
            if current_size + sentence_len > self.chunk_size and current_chunk:
                raw_chunks.append(current_chunk)
                overlap_sentences = self._get_overlap_sentences(
                    current_chunk, self.chunk_overlap
                )
                current_chunk = overlap_sentences[:]
                current_size = sum(len(s) for s in current_chunk)
            current_chunk.append(sentence)
            current_size += sentence_len

        if current_chunk:
            raw_chunks.append(current_chunk)

        for i, chunk_sentences in enumerate(raw_chunks):
            chunk_text = " ".join(chunk_sentences).strip()
            if not chunk_text:
                continue
            chunk_meta = dict(base_metadata)
            chunk_meta["chunk_index"] = i
            chunk_meta["total_chunks"] = len(raw_chunks)
            chunks.append(Chunk(text=chunk_text, index=i, metadata=chunk_meta))

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences.

        Uses a regex-based approach that handles common abbreviations.
        """
        text = re.sub(r"\s+", " ", text).strip()

        sentences = re.split(r"(?<=[.!?。！？])\s+(?=[A-Z\u4e00-\u9fa5])", text)

        sentences = [s.strip() for s in sentences if s.strip()]

        result: list[str] = []
        for sentence in sentences:
            if len(sentence) > self.chunk_size:
                parts = re.split(r"([;；:：,，])", sentence)
                current = ""
                for part in parts:
                    if len(current) + len(part) > self.chunk_size and current:
                        result.append(current.strip())
                        current = part
                    else:
                        current += part
                if current.strip():
                    result.append(current.strip())
            else:
                result.append(sentence)

        return result

    def _get_overlap_sentences(
        self, sentences: list[str], overlap_chars: int
    ) -> list[str]:
        """Get sentences from the end that total roughly overlap_chars characters."""
        overlap: list[str] = []
        total = 0
        for s in reversed(sentences):
            if total + len(s) <= overlap_chars:
                overlap.insert(0, s)
                total += len(s)
            else:
                break
        return overlap

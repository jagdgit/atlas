"""Text chunking.

A deliberately simple, dependency-free word-window chunker with overlap. Good
enough for the foundation; smarter (sentence/semantic) chunking can replace this
behind the same interface later.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    token_count: int  # approximate: whitespace-delimited words


def chunk_text(
    text: str, *, max_words: int = 200, overlap: int = 40
) -> list[Chunk]:
    """Split text into overlapping word windows.

    ``overlap`` words are repeated between consecutive chunks to preserve context
    across boundaries. Empty/whitespace text yields no chunks.
    """
    if max_words <= 0:
        raise ValueError("max_words must be positive")
    if overlap < 0 or overlap >= max_words:
        raise ValueError("overlap must be >= 0 and < max_words")

    words = text.split()
    if not words:
        return []

    step = max_words - overlap
    chunks: list[Chunk] = []
    ordinal = 0
    for start in range(0, len(words), step):
        window = words[start : start + max_words]
        if not window:
            break
        chunks.append(
            Chunk(ordinal=ordinal, content=" ".join(window), token_count=len(window))
        )
        ordinal += 1
        if start + max_words >= len(words):
            break
    return chunks

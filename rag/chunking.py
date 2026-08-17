"""Chunking (spec.md §15).

Splits each extracted segment (page/slide/sheet/section) into overlapping
windows sized in "tokens". We approximate tokens as whitespace-split words
rather than pulling in a real tokenizer — close enough to tune chunk_size/
overlap against, and cheap. Chunks never span segments, so `page`/`section`
metadata on a chunk is always exact, never a guess about where a page break
fell inside a merged blob.

Chunk size/overlap are configurable (config.defaults / future settings UI),
never hard-coded at the call site — spec.md §16.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.defaults import DEFAULT_CHUNK_OVERLAP_TOKENS, DEFAULT_CHUNK_SIZE_TOKENS
from documents.base import ExtractedSegment


@dataclass
class Chunk:
    text: str
    chunk_index: int
    page: int | None = None
    section: str | None = None


def chunk_segments(
    segments: list[ExtractedSegment],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
    overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    chunk_index = 0

    for segment in segments:
        words = segment.text.split()
        if not words:
            continue

        start = 0
        while start < len(words):
            window = words[start : start + chunk_size]
            text = " ".join(window).strip()
            if text:
                chunks.append(
                    Chunk(
                        text=text,
                        chunk_index=chunk_index,
                        page=segment.page,
                        section=segment.section,
                    )
                )
                chunk_index += 1
            if start + chunk_size >= len(words):
                break
            start += step

    return chunks

"""Document parser contract.

Every format parser (`pdf.py`, `docx.py`, ...) takes a file path and returns
an `ExtractedDocument`: a flat list of segments, each roughly a page/slide/
sheet/section. `rag/chunking.py` later splits each segment's text further by
token count; segments are what let a chunk keep a meaningful `page`/`section`
label instead of just a byte offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractedSegment:
    text: str
    page: int | None = None
    section: str | None = None


@dataclass
class ExtractedDocument:
    segments: list[ExtractedSegment]
    source_type: str


class DocumentParser(Protocol):
    extensions: tuple[str, ...]

    def extract(self, path: Path) -> ExtractedDocument: ...


class DocumentParseError(Exception):
    """Raised by a parser on a corrupt/unreadable file. Callers (ingestion)
    catch this, mark the document 'failed', and continue with other files
    (spec.md §32: 'Log file-specific failure and continue processing
    other files.')."""

    pass

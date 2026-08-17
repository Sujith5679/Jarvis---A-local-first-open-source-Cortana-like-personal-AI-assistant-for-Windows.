"""Extension -> parser dispatch.

`get_parser(path)` returns None for unsupported extensions; callers
(rag/ingestion.py) mark such files `status='unsupported'` and move on
(spec.md §32: unsupported/failed files never block the rest of ingestion).
"""

from __future__ import annotations

from pathlib import Path

from documents.base import DocumentParser
from documents.docx import DocxParser
from documents.pdf import PdfParser
from documents.pptx import PptxParser
from documents.text import HtmlParser, PlainTextParser
from documents.xlsx import XlsxParser

_PARSERS: list[DocumentParser] = [
    PdfParser(),
    DocxParser(),
    PptxParser(),
    XlsxParser(),
    HtmlParser(),
    PlainTextParser(),
]

_BY_EXTENSION: dict[str, DocumentParser] = {
    ext: parser for parser in _PARSERS for ext in parser.extensions
}

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(_BY_EXTENSION.keys())


def get_parser(path: Path) -> DocumentParser | None:
    return _BY_EXTENSION.get(path.suffix.lower())


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in _BY_EXTENSION

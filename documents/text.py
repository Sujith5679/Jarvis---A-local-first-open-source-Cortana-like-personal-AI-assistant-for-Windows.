"""Plain-text, Markdown, CSV, JSON, HTML, and source-code extraction.

Everything here reduces to "read this file as text" — HTML additionally goes
through BeautifulSoup to strip tags/scripts down to readable content. Each
file becomes a single segment; `rag/chunking.py` splits it further by token
count.
"""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from documents.base import DocumentParseError, ExtractedDocument, ExtractedSegment

PLAIN_TEXT_EXTENSIONS = (
    ".txt", ".md", ".csv", ".json",
    ".py", ".java", ".js", ".ts", ".c", ".cpp", ".h", ".hpp",
)
HTML_EXTENSIONS = (".html", ".htm")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError(f"Could not decode {path.name} as text")


class PlainTextParser:
    extensions = PLAIN_TEXT_EXTENSIONS

    def extract(self, path: Path) -> ExtractedDocument:
        try:
            text = _read_text(path).strip()
        except OSError as exc:
            raise DocumentParseError(f"Could not read file: {exc}") from exc

        source_type = path.suffix.lstrip(".").lower() or "text"
        segments = [ExtractedSegment(text=text)] if text else []
        return ExtractedDocument(segments=segments, source_type=source_type)


class HtmlParser:
    extensions = HTML_EXTENSIONS

    def extract(self, path: Path) -> ExtractedDocument:
        try:
            raw = _read_text(path)
        except OSError as exc:
            raise DocumentParseError(f"Could not read file: {exc}") from exc

        try:
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator="\n").strip()
            # Collapse runs of blank lines left behind by tag stripping.
            text = "\n".join(line for line in text.splitlines() if line.strip())
        except Exception as exc:
            raise DocumentParseError(f"Could not parse HTML: {exc}") from exc

        segments = [ExtractedSegment(text=text)] if text else []
        return ExtractedDocument(segments=segments, source_type="html")

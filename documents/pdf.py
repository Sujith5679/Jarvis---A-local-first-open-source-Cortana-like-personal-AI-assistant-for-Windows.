"""PDF extraction via PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from documents.base import DocumentParseError, ExtractedDocument, ExtractedSegment


class PdfParser:
    extensions = (".pdf",)

    def extract(self, path: Path) -> ExtractedDocument:
        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            raise DocumentParseError(f"Could not open PDF: {exc}") from exc

        segments: list[ExtractedSegment] = []
        try:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
                text = page.get_text().strip()
                if text:
                    segments.append(ExtractedSegment(text=text, page=page_index + 1))
        except Exception as exc:
            raise DocumentParseError(f"Failed reading PDF pages: {exc}") from exc
        finally:
            doc.close()

        return ExtractedDocument(segments=segments, source_type="pdf")

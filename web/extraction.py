"""Readable-text extraction from fetched web pages (spec.md §23).

Uses readability-lxml (a Python port of Mozilla's Readability) to strip
navigation/ads/boilerplate down to the main article content, falling back to
a plain BeautifulSoup tag-strip (the same approach as
`documents/text.py`'s local HTML parser) if Readability can't parse the
page. Output is capped — never hand a whole raw page to the LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bs4 import BeautifulSoup
from config.defaults import DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS
from readability import Document

logger = logging.getLogger("jarvis.web.extraction")


@dataclass
class ExtractedPage:
    title: str
    text: str
    truncated: bool


def _plain_tag_strip(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text().strip() if soup.title else ""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n").strip()
    return title, text


def extract_readable_text(html: str, url: str = "") -> ExtractedPage:
    title = ""
    text = ""
    try:
        doc = Document(html)
        title = doc.short_title() or ""
        summary_html = doc.summary()
        _, text = _plain_tag_strip(summary_html)
    except Exception as exc:
        logger.warning("Readability extraction failed for %s: %s", url, exc)

    if not text:
        try:
            fallback_title, text = _plain_tag_strip(html)
            title = title or fallback_title
        except Exception as exc:
            logger.warning("Fallback extraction failed for %s: %s", url, exc)

    text = "\n".join(line for line in text.splitlines() if line.strip())

    truncated = len(text) > DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS
    if truncated:
        text = text[:DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS]

    return ExtractedPage(title=title, text=text, truncated=truncated)

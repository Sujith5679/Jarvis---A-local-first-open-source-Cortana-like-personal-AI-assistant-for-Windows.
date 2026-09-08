"""Markdown-to-HTML renderer for assistant chat messages.

Converts LLM markdown output (tables, headers, bold/italic, bullet lists,
code blocks, links, blockquotes) into HTML that Qt's QTextBrowser can
display.  Only used for *assistant* messages — user and error messages
stay plain-escaped text so nothing the user types is reinterpreted.

Falls back to simple ``html.escape(text).replace("\\n", "<br>")`` if the
``markdown`` library is unavailable, per spec.md §32's graceful-degradation
rule: a missing optional dependency should degrade to the previous behavior,
never crash.
"""

from __future__ import annotations

import html
import logging

logger = logging.getLogger("jarvis.ui.markdown_render")

try:
    import markdown as _md

    _MD_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MD_AVAILABLE = False
    logger.warning(
        "The 'markdown' package is not installed — assistant messages will "
        "render as plain text.  Install it with:  pip install markdown>=3.6"
    )

_EXTENSIONS = [
    "tables",       # | col | col | tables
    "fenced_code",  # ```lang ... ``` code blocks
    "nl2br",        # single newlines → <br> (matches LLM output style)
    "sane_lists",   # tighter list-item detection
]


def render_markdown(text: str) -> str:
    """Return HTML from *text* using ``markdown`` extensions.

    If the library is missing the return value is the same
    ``html.escape(text).replace("\\n", "<br>")`` that ``messages.py``
    used before this module existed — so the UI never breaks, it just
    looks less pretty.
    """
    if not _MD_AVAILABLE:
        return html.escape(text).replace("\n", "<br>")
    try:
        return _md.markdown(text, extensions=_EXTENSIONS)
    except Exception:
        logger.exception("Markdown rendering failed; falling back to plain text")
        return html.escape(text).replace("\n", "<br>")

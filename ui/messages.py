"""Chat log rendering widget.

Renders messages as solid-colored, role-aligned blocks (user right, Jarvis
left) rather than the previous plain "Label: text" lines. Qt's rich text
engine only supports a CSS 2.1 subset - live-verified (offscreen render,
pixel-checked) that `border-radius` is silently ignored, so there's no way
to get literally rounded bubble corners without a custom paint delegate.
What's here (a colored, padded, role-aligned block via a nested HTML table)
is the real ceiling for "bubble-ish" while staying inside QTextEdit rather
than a bigger custom-widget rewrite - still a clear visual step up from
undecorated text.

Citations (spec.md §18/§41, agent/graph.py's _extract_citations) are
rendered as small clickable chips under an assistant message - previously
captured and stored (storage/repositories/conversations.py's `citations`
column) but never actually shown anywhere. Clicking one opens the file (or
URL) directly; citation targets are kept in an in-memory id->target table
rather than encoded into the link href itself, so arbitrary
paths/filenames (spaces, colons, unicode) never have to round-trip through
URL escaping/QUrl parsing.
"""

from __future__ import annotations

import html
import json
import logging
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QTextBrowser

from ui.markdown_render import render_markdown
from ui.theme import LIGHT, Theme

logger = logging.getLogger("jarvis.ui.messages")


class ChatLog(QTextBrowser):
    """Read-only, auto-scrolling chat transcript.

    QTextBrowser rather than plain QTextEdit specifically for
    `anchorClicked`/`setOpenLinks` (live-verified: neither exists on
    QTextEdit, only on its QTextBrowser subclass) - needed to intercept
    citation-chip clicks ourselves instead of Qt trying to "navigate" to
    them. Rich-text rendering is otherwise identical to QTextEdit.
    """

    def __init__(self, parent=None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)  # citation links are handled ourselves, see _on_anchor_clicked
        self.anchorClicked.connect(self._on_anchor_clicked)
        self.theme = theme
        self._citation_targets: dict[str, dict] = {}
        self._next_citation_id = 0
        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            f"QTextBrowser {{ background: {self.theme.surface_bg}; color: {self.theme.text}; "
            f"font-size: 13px; border: none; padding: 8px; }}"
        )

    def apply_theme(self, theme: Theme) -> None:
        """Restyles the widget chrome; already-rendered messages keep their
        old colors baked into their HTML (Qt doesn't re-style HTML already
        appended). Callers that want the visible transcript to fully switch
        too should re-render via load_history() after this."""
        self.theme = theme
        self._apply_stylesheet()

    def _register_citation(self, kind: str, target: str) -> str:
        key = f"c{self._next_citation_id}"
        self._next_citation_id += 1
        self._citation_targets[key] = {"kind": kind, "target": target}
        return key

    def _citation_chip_html(self, citation: dict) -> str:
        if citation.get("path"):  # search_files/read_file shape
            filename = citation.get("filename") or citation.get("path")
            page = citation.get("page")
            label = f"\U0001f4c4 {filename}" + (f" (p.{page})" if page else "")
            key = self._register_citation("file", citation["path"])
        elif citation.get("url"):  # web_search/open_webpage shape
            fallback = citation.get("domain") or citation["url"]
            label = "\U0001f517 " + (citation.get("title") or fallback)
            key = self._register_citation("url", citation["url"])
        else:
            return ""
        muted = self.theme.muted_text
        return (
            f'<a href="jarvis-citation:{key}" style="color:{muted}; text-decoration:underline;">'
            f"{html.escape(label)}</a>"
        )

    def _markdown_inline_css(self, fg: str, bg: str) -> str:
        """Inline CSS for markdown-generated HTML elements inside an assistant
        bubble.  Qt's rich-text engine supports a CSS 2.1 subset — these rules
        cover everything the ``markdown`` library emits with the enabled
        extensions (tables, fenced_code, nl2br, sane_lists)."""
        t = self.theme
        # Code background: slightly tinted surface for contrast
        code_bg = t.border  # subtle contrast against bubble bg
        return (
            f"<style>"
            # --- Tables -------------------------------------------------
            f"table {{ border-collapse: collapse; width: 100%; margin: 6px 0; }}"
            f"th, td {{ border: 1px solid {t.muted_text}; padding: 4px 8px; "
            f"  text-align: left; color: {fg}; font-size: 12px; }}"
            f"th {{ background-color: {code_bg}; font-weight: 600; }}"
            # --- Headings -----------------------------------------------
            f"h1 {{ font-size: 17px; margin: 8px 0 4px; color: {fg}; }}"
            f"h2 {{ font-size: 15px; margin: 8px 0 4px; color: {fg}; }}"
            f"h3 {{ font-size: 14px; margin: 6px 0 3px; color: {fg}; }}"
            f"h4, h5, h6 {{ font-size: 13px; margin: 4px 0 2px; color: {fg}; }}"
            # --- Code ---------------------------------------------------
            f"code {{ background: {code_bg}; padding: 1px 4px; font-size: 12px; "
            f"  font-family: Consolas, monospace; }}"
            f"pre {{ background: {code_bg}; padding: 8px; margin: 4px 0; "
            f"  font-size: 12px; font-family: Consolas, monospace; "
            f"  white-space: pre-wrap; word-wrap: break-word; }}"
            # --- Lists --------------------------------------------------
            f"ul, ol {{ margin: 4px 0 4px 16px; padding: 0; }}"
            f"li {{ margin: 2px 0; color: {fg}; }}"
            # --- Links --------------------------------------------------
            f"a {{ color: {t.accent}; text-decoration: underline; }}"
            # --- Blockquotes --------------------------------------------
            f"blockquote {{ border-left: 3px solid {t.accent}; margin: 4px 0; "
            f"  padding: 2px 8px; color: {t.muted_text}; }}"
            # --- Horizontal rules ---------------------------------------
            f"hr {{ border: none; border-top: 1px solid {t.muted_text}; margin: 8px 0; }}"
            # --- Paragraphs (tighter spacing inside bubbles) ------------
            f"p {{ margin: 4px 0; }}"
            f"</style>"
        )

    def _bubble_html(self, role: str, text: str, citations: list[dict] | None) -> str:
        if role == "user":
            align, bg, fg = "right", self.theme.user_bubble_bg, self.theme.user_bubble_text
            body_html = html.escape(text).replace("\n", "<br>")
        elif role == "error":
            align, bg, fg = "left", self.theme.surface_bg, self.theme.error_text
            body_html = html.escape(text).replace("\n", "<br>")
        else:  # assistant — render markdown
            align = "left"
            bg, fg = self.theme.assistant_bubble_bg, self.theme.assistant_bubble_text
            body_html = self._markdown_inline_css(fg, bg) + render_markdown(text)

        chips = [c for c in (self._citation_chip_html(c) for c in citations or []) if c]
        citations_html = (
            f'<div style="margin-top:6px; font-size:11px;">{" &nbsp; ".join(chips)}</div>'
            if chips
            else ""
        )

        return (
            f'<table width="100%" cellspacing="0" style="margin:4px 0;"><tr><td align="{align}">'
            f'<table cellspacing="0"><tr><td style="background-color:{bg}; padding:8px 10px;">'
            f'<span style="color:{fg};">{body_html}</span>'
            f"{citations_html}"
            f"</td></tr></table>"
            f"</td></tr></table>"
        )

    def append_message(self, role: str, text: str, citations: list[dict] | None = None) -> None:
        self.append(self._bubble_html(role, text, citations))
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_status(self, text: str) -> None:
        style = (
            f"margin:4px 0; color:{self.theme.status_text}; font-style:italic; "
            f"text-align:center;"
        )
        self.append(f'<p style="{style}">{html.escape(text)}</p>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def load_history(self, messages: list[dict]) -> None:
        """Replaces the whole log with `messages` (storage.repositories.
        conversations.get_messages()'s shape) — used when switching to a
        different (existing) conversation (ui/history.py), or to re-render
        with a new theme. "tool" role messages aren't rendered, same as
        they're excluded from to_llm_messages() — they're turn-scoped
        plumbing, not something a person reads back."""
        self.clear()
        self._citation_targets = {}
        self._next_citation_id = 0
        for message in messages:
            if message["role"] == "tool":
                continue
            citations = None
            raw = message.get("citations")
            if raw:
                try:
                    citations = json.loads(raw)
                except (TypeError, ValueError):
                    logger.warning(
                        "Could not parse stored citations for message %r", message.get("id")
                    )
            self.append_message(message["role"], message["content"], citations)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() != "jarvis-citation":
            QDesktopServices.openUrl(url)
            return
        entry = self._citation_targets.get(url.path())
        if entry is None:
            return
        if entry["kind"] == "file":
            path = entry["target"]
            try:
                os.startfile(path)  # noqa: S606 - opening a file just shown to the user as a citation, not LLM/tool-controlled input
            except OSError as exc:
                logger.warning("Could not open citation file %r: %s", path, exc)
                QMessageBox.warning(self, "Could not open file", f"{path}\n\n{exc}")
        else:
            QDesktopServices.openUrl(QUrl(entry["target"]))

"""Chat log rendering widget.

Kept intentionally simple (a styled read-only text log) rather than a custom
bubble-list widget — it's compact, scrolls natively, and is easy to extend
with citations/tool-call annotations in later phases without a rewrite.
"""

from __future__ import annotations

import html

from PySide6.QtWidgets import QTextEdit

_ROLE_STYLES = {
    "user": ("You", "#2563eb"),
    "assistant": ("Jarvis", "#16a34a"),
    "error": ("Jarvis", "#dc2626"),
    "system": ("System", "#6b7280"),
}


class ChatLog(QTextEdit):
    """Read-only, auto-scrolling chat transcript."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet(
            "QTextEdit { background: #ffffff; font-size: 13px; border: none; padding: 8px; }"
        )

    def append_message(self, role: str, text: str) -> None:
        label, color = _ROLE_STYLES.get(role, ("Jarvis", "#111827"))
        safe_text = html.escape(text).replace("\n", "<br>")
        self.append(
            f'<p style="margin:4px 0;">'
            f'<b style="color:{color};">{label}:</b> '
            f'<span style="color:#111827;">{safe_text}</span>'
            f"</p>"
        )
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_status(self, text: str) -> None:
        style = "margin:4px 0; color:#9ca3af; font-style:italic;"
        self.append(f'<p style="{style}">{html.escape(text)}</p>')
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def load_history(self, messages: list[dict]) -> None:
        """Replaces the whole log with `messages` (storage.repositories.
        conversations.get_messages()'s shape) — used when switching to a
        different (existing) conversation (ui/history.py). "tool" role
        messages aren't rendered, same as they're excluded from
        to_llm_messages() — they're turn-scoped plumbing, not something a
        person reads back."""
        self.clear()
        for message in messages:
            if message["role"] == "tool":
                continue
            self.append_message(message["role"], message["content"])

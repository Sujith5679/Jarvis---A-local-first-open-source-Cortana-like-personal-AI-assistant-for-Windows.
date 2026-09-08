"""Conversation history dialog — browse and resume past conversations, or
delete one. Opened from ChatWindow's "Chat" menu ("History...").

A conversation is switched into *immediately* on open (no restart
needed) since it's just loading rows already in SQLite.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from storage.repositories import conversations as conv_repo


def _display_title(conversation: dict) -> str:
    title = conversation.get("title")
    return title if title else "(untitled conversation)"


class ConversationHistoryDialog(QDialog):
    def __init__(self, chat_window, parent=None) -> None:
        super().__init__(parent)
        self.chat_window = chat_window  # ui.chat_window.ChatWindow
        self.setWindowTitle("Conversation History")
        self.resize(440, 420)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Double-click a conversation to switch to it, or select one and use the "
            "buttons below.",
            self,
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#6b7280; font-size: 11px;")
        layout.addWidget(info)

        self.conversation_list = QListWidget(self)
        self.conversation_list.itemDoubleClicked.connect(lambda _item: self._on_open())
        layout.addWidget(self.conversation_list, stretch=1)

        button_row = QHBoxLayout()
        self.open_button = QPushButton("Open", self)
        self.open_button.clicked.connect(self._on_open)
        button_row.addWidget(self.open_button)

        self.delete_button = QPushButton("Delete", self)
        self.delete_button.clicked.connect(self._on_delete)
        button_row.addWidget(self.delete_button)
        layout.addLayout(button_row)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._conversations: list[dict] = []
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._conversations = conv_repo.list_conversations()
        self.conversation_list.clear()
        for conversation in self._conversations:
            is_current = conversation["id"] == self.chat_window.conversation_id
            current_marker = " (current)" if is_current else ""
            timestamp = conversation["updated_at"][:19]
            label = f"{_display_title(conversation)}{current_marker} — {timestamp}"
            self.conversation_list.addItem(label)

    def _selected_conversation(self) -> dict | None:
        row = self.conversation_list.currentRow()
        if row < 0 or row >= len(self._conversations):
            return None
        return self._conversations[row]

    def _on_open(self) -> None:
        conversation = self._selected_conversation()
        if conversation is None:
            return
        self.chat_window.switch_to_conversation(conversation["id"])
        self.accept()

    def _on_delete(self) -> None:
        conversation = self._selected_conversation()
        if conversation is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete conversation",
            f"Permanently delete {_display_title(conversation)!r}? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        conv_repo.delete_conversation(conversation["id"])
        if conversation["id"] == self.chat_window.conversation_id:
            # The conversation on screen just vanished from under it -
            # never leave the window pointed at a conversation_id that no
            # longer exists (the next message would violate the messages
            # table's FK to conversations).
            self.chat_window.start_new_conversation()
        self._refresh_list()

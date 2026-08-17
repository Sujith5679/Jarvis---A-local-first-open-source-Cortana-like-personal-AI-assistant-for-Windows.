"""The floating chat popup (spec.md §25).

Compact, resizable, draggable (via native window chrome), Facebook/Google-Chat
style single conversation view. UI states implemented so far: idle, thinking,
error. Tool-execution / waiting-for-confirmation / listening / speaking
states are added in Phases 2-5 without changing this window's shape.

The agent turn runs on a background QThread (`ChatTurnWorker`) so a slow LLM
call never freezes the UI thread (spec.md §42).
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from agent.graph import Agent, build_agent
from agent.state import AgentState
from app.bootstrap import BootstrapContext
from storage.repositories import conversations as conv_repo
from ui.messages import ChatLog

logger = logging.getLogger("jarvis.ui.chat_window")


class ChatTurnWorker(QThread):
    """Runs one agent turn off the UI thread."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, agent: Agent, conversation_id: int, user_message: str) -> None:
        super().__init__()
        self.agent = agent
        self.conversation_id = conversation_id
        self.user_message = user_message

    def run(self) -> None:
        try:
            state: AgentState = asyncio.run(
                self.agent.run_turn(self.conversation_id, self.user_message)
            )
            self.succeeded.emit(dict(state))
        except Exception as exc:  # pragma: no cover - defensive, agent already catches its own errors
            logger.exception("Unexpected error running agent turn")
            self.failed.emit(str(exc))


class ChatWindow(QMainWindow):
    def __init__(self, ctx: BootstrapContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.agent = build_agent(ctx.settings)
        self.conversation_id = conv_repo.create_conversation()
        self._worker: ChatTurnWorker | None = None

        self.setWindowTitle("JARVIS")
        self.resize(380, 540)
        self.setMinimumSize(300, 400)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chat_log = ChatLog(central)
        layout.addWidget(self.chat_log, stretch=1)

        self.status_label = QLabel("", central)
        self.status_label.setStyleSheet("color:#9ca3af; font-style:italic; padding: 2px 8px;")
        layout.addWidget(self.status_label)

        input_row = QWidget(central)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(8, 4, 8, 8)

        self.input_field = QLineEdit(input_row)
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.returnPressed.connect(self._on_send_clicked)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_button = QPushButton(">", input_row)
        self.send_button.setFixedWidth(36)
        self.send_button.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self.send_button)

        layout.addWidget(input_row)
        self.setCentralWidget(central)

        self.chat_log.append_message("assistant", "How can I help?")

    # --- UI state management -------------------------------------------------

    def _set_thinking(self, thinking: bool) -> None:
        self.input_field.setEnabled(not thinking)
        self.send_button.setEnabled(not thinking)
        self.status_label.setText("Jarvis is thinking..." if thinking else "")
        if not thinking:
            self.input_field.setFocus()

    # --- Send flow -------------------------------------------------------------

    def _on_send_clicked(self) -> None:
        text = self.input_field.text().strip()
        if not text:
            return

        self.chat_log.append_message("user", text)
        self.input_field.clear()
        self._set_thinking(True)

        self._worker = ChatTurnWorker(self.agent, self.conversation_id, text)
        self._worker.succeeded.connect(self._on_turn_succeeded)
        self._worker.failed.connect(self._on_turn_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_turn_succeeded(self, state: dict) -> None:
        self._set_thinking(False)
        if state.get("error"):
            self.chat_log.append_message("error", f"Sorry, I ran into a problem: {state['error']}")
        else:
            self.chat_log.append_message("assistant", state.get("response") or "")

    def _on_turn_failed(self, message: str) -> None:
        self._set_thinking(False)
        self.chat_log.append_message("error", f"Unexpected error: {message}")


def run(ctx: BootstrapContext) -> int:
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    window = ChatWindow(ctx)
    window.show()
    return app.exec()

"""The floating chat popup (spec.md §25).

Compact, resizable, draggable (via native window chrome), Facebook/Google-Chat
style single conversation view. UI states implemented: idle, thinking,
listening, speaking, waiting-for-confirmation, error.

The agent turn runs on a background QThread (`ChatTurnWorker`) so a slow LLM
call never freezes the UI thread (spec.md §42). Reminder notifications
(spec.md §22) are wired here too: `SchedulerService` polls on its own
thread and crosses back via a Qt signal to `NotificationService`.

Voice (spec.md §24) is push-to-talk: hold the mic button to record, release
to transcribe + send. `AudioRecorder.start()/.stop()` don't block (PortAudio
runs its own callback thread), but transcription, the agent turn, and TTS
playback all run on `VoiceTurnWorker` off the UI thread. Voice is entirely
optional — `JARVIS_ENABLE_VOICE=false` hides the mic button, and any STT/TTS
failure degrades to text-only rather than blocking the user (spec.md §32).

Windows integration (spec.md §57 Phase 6, revised): `run()` wires up a
system tray icon (`ui/tray.py`) for quick actions (pause indexing, voice
toggle, reindex, view logs) while the app is open — but the *process*
itself now runs on demand rather than staying resident: closing the window
(the titlebar X, or tray Quit) fully exits (see `closeEvent`), and the
global hotkey lives entirely in the separate, lightweight
`app/supervisor.py` process instead of here, so nothing about this heavy
process (agent, RAG, voice models) needs to stay loaded in memory just to
keep Ctrl+Space available. Tray registration is still best-effort — if it
fails, the window just runs as a normal top-level window (spec.md §32's
graceful-degradation rule, same as voice).
"""

from __future__ import annotations

import asyncio
import logging

from agent.graph import Agent, build_agent
from agent.state import AgentState
from app.bootstrap import BootstrapContext
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from scheduler.service import SchedulerService
from storage.repositories import conversations as conv_repo
from voice.audio import AudioRecorder, MicrophoneUnavailableError, play_audio
from voice.stt import TranscriptionError
from voice.stt import transcribe as stt_transcribe
from voice.tts import SynthesisError
from voice.tts import synthesize as tts_synthesize

from ui.mcp_settings import MCPServersDialog
from ui.messages import ChatLog
from ui.notifications import NotificationService
from ui.settings import FoldersDialog
from ui.usage_dialog import UsageDialog

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
        except Exception as exc:  # pragma: no cover - defensive; agent handles its own errors
            logger.exception("Unexpected error running agent turn")
            self.failed.emit(str(exc))


class MCPDiscoveryWorker(QThread):
    """Connects to every configured+enabled MCP server (integrations/mcp/)
    and registers their tools into the agent's tool registry, off the UI
    thread — server startup (especially npx-spawned ones) can take a few
    seconds and must never block the UI (spec.md §42), same reasoning as
    IndexingWorker (ui/settings.py). Tools become available for the *next*
    agent turn once this finishes — a turn already in flight when discovery
    completes doesn't retroactively gain them.

    No connection is kept open once this finishes — each MCP tool call
    later opens its own short-lived connection (integrations/mcp/bridge.py's
    module docstring explains why: an mcp.Client's background tasks are
    tied to the event loop that opened it, and that loop is this worker's
    own asyncio.run() call, which is long gone by the time a tool actually
    gets invoked from a separate agent turn)."""

    finished_ok = Signal(int)  # number of MCP servers successfully reached
    failed = Signal(str)

    def __init__(self, registry) -> None:
        super().__init__()
        self.registry = registry

    def run(self) -> None:
        from integrations.mcp.bridge import discover_and_register

        try:
            reached = asyncio.run(discover_and_register(self.registry))
            self.finished_ok.emit(reached)
        except Exception as exc:  # pragma: no cover - defensive; discover_and_register
            # itself never raises (per-server failures are caught internally) - this only
            # catches a genuinely unexpected bug, so MCP can never take the app down.
            logger.exception("MCP discovery failed unexpectedly")
            self.failed.emit(str(exc))


class ConfirmTurnWorker(QThread):
    """Runs Agent.confirm_and_execute() off the UI thread."""

    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(
        self, agent: Agent, conversation_id: int, tool_name: str, arguments: dict, approved: bool
    ) -> None:
        super().__init__()
        self.agent = agent
        self.conversation_id = conversation_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.approved = approved

    def run(self) -> None:
        try:
            state: AgentState = asyncio.run(
                self.agent.confirm_and_execute(
                    self.conversation_id, self.tool_name, self.arguments, approved=self.approved
                )
            )
            self.succeeded.emit(dict(state))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error running confirmed tool")
            self.failed.emit(str(exc))


class VoiceTurnWorker(QThread):
    """Transcribe -> agent turn -> (optionally) synthesize + speak the reply,
    entirely off the UI thread. Each stage can fail independently without
    taking down the others — a transcription failure never touches the
    agent, and a TTS failure never hides the (already-shown) text reply."""

    transcribed = Signal(str)
    succeeded = Signal(dict)
    failed = Signal(str)
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(
        self,
        agent: Agent,
        conversation_id: int,
        audio,
        sample_rate: int,
        *,
        speak_reply: bool,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.conversation_id = conversation_id
        self.audio = audio
        self.sample_rate = sample_rate
        self.speak_reply = speak_reply

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        session_id = str(self.conversation_id)
        try:
            text = (
                await stt_transcribe(self.audio, self.sample_rate, session_id=session_id)
            ).strip()
        except TranscriptionError as exc:
            self.failed.emit(f"Could not understand that: {exc}")
            return

        if not text:
            self.failed.emit("I didn't catch that — try again, or type your message.")
            return
        self.transcribed.emit(text)

        try:
            state: AgentState = await self.agent.run_turn(self.conversation_id, text)
        except Exception as exc:  # pragma: no cover - defensive; agent handles its own errors
            logger.exception("Unexpected error running voice-originated agent turn")
            self.failed.emit(str(exc))
            return

        self.succeeded.emit(dict(state))

        should_speak = (
            self.speak_reply
            and not state.get("requires_confirmation")
            and not state.get("error")
            and state.get("response")
        )
        if should_speak:
            try:
                audio, sr = await tts_synthesize(state["response"], session_id=session_id)
                self.started_speaking.emit()
                play_audio(audio, sr)
            except SynthesisError as exc:
                logger.warning("TTS failed; reply already shown as text: %s", exc)
            finally:
                self.finished_speaking.emit()


class ChatWindow(QMainWindow):
    def __init__(self, ctx: BootstrapContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.agent = build_agent(ctx.settings)
        self.conversation_id = conv_repo.create_conversation()
        self._worker: ChatTurnWorker | ConfirmTurnWorker | VoiceTurnWorker | None = None
        self._mcp_server_count = 0  # how many MCP servers are currently reachable
        self._mcp_worker: MCPDiscoveryWorker | None = None
        self._mcp_reconnect_callback = None
        self._start_mcp_discovery()
        # Set by run() below after construction, if a tray is available on
        # this platform — purely a convenience menu (pause indexing,
        # voice toggle, reindex, view logs) while the app happens to be
        # open; the global hotkey now lives entirely in app/supervisor.py.
        self.tray = None

        self.setWindowTitle("JARVIS")
        self.resize(380, 540)
        self.setMinimumSize(300, 400)

        settings_menu = self.menuBar().addMenu("Settings")
        manage_folders_action = settings_menu.addAction("Settings...")
        manage_folders_action.triggered.connect(self._open_folders_dialog)
        usage_action = settings_menu.addAction("Usage && Costs...")
        usage_action.triggered.connect(self._open_usage_dialog)
        mcp_action = settings_menu.addAction("MCP Servers...")
        mcp_action.triggered.connect(self._open_mcp_dialog)

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

        self._recorder: AudioRecorder | None = None
        # Runtime on/off, independent of the JARVIS_ENABLE_VOICE startup
        # switch below — this is what ui/tray.py's "Start/Stop voice" toggle
        # flips. Only meaningful (and only exposed in the tray menu) when
        # voice_available is True; there's no recorder to pause otherwise.
        self.voice_enabled = ctx.settings.jarvis_enable_voice
        if ctx.settings.jarvis_enable_voice:
            self._recorder = AudioRecorder()
            self.mic_button = QPushButton("🎤", input_row)
            self.mic_button.setFixedWidth(36)
            self.mic_button.setToolTip("Hold to talk")
            self.mic_button.pressed.connect(self._on_mic_pressed)
            self.mic_button.released.connect(self._on_mic_released)
            input_layout.addWidget(self.mic_button)

        self.send_button = QPushButton(">", input_row)
        self.send_button.setFixedWidth(36)
        self.send_button.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self.send_button)

        layout.addWidget(input_row)
        self.setCentralWidget(central)

        self.chat_log.append_message("assistant", "How can I help?")

        self.notifications = NotificationService()
        self.scheduler = SchedulerService()
        self.scheduler.bridge.reminder_fired.connect(self._on_reminder_fired)
        self.scheduler.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        # Closing the window (the titlebar X, or ui.tray.TrayIcon.quit_app())
        # always fully exits — app/supervisor.py is what stays resident for
        # the global hotkey now, so this process only needs to run while
        # actually in use. Ctrl+Space (or the supervisor's own tray icon)
        # launches a fresh instance the next time it's needed. Nothing to
        # tear down for MCP here — no connection is ever kept open between
        # calls (integrations/mcp/bridge.py's module docstring explains why).
        self.scheduler.stop()
        super().closeEvent(event)

    # --- MCP (integrations/mcp/) ------------------------------------------
    #
    # _start_mcp_discovery() and reconnect_mcp_servers() must never run
    # concurrently — discover_and_register() mutates the shared tool
    # registry directly from the worker thread, so two overlapping calls
    # (e.g. the initial startup discovery still in flight when the user
    # opens Settings and clicks "Reconnect Now" right away) would both
    # register into the same registry and collide. Guarded the same way
    # ui/settings.py's IndexingWorker/_start_indexing() already guards
    # against a second indexing run starting mid-first-run: refuse to
    # start while `_mcp_worker.isRunning()`, rather than trying to
    # reconcile two interleaved results afterward.

    def _start_mcp_discovery(self) -> bool:
        """Returns True if a discovery run was actually started, False if
        one was already in progress."""
        if self._mcp_worker is not None and self._mcp_worker.isRunning():
            return False
        worker = MCPDiscoveryWorker(self.agent.tool_registry)
        worker.finished_ok.connect(self._on_mcp_discovery_finished)
        worker.failed.connect(lambda msg: logger.warning("MCP discovery failed: %s", msg))
        # Clearing self._mcp_worker must happen before deleteLater() runs -
        # deleteLater() destroys the underlying C++ QThread object, and any
        # later self._mcp_worker.isRunning() call (the busy-guard above) on
        # a reference to that now-deleted object raises
        # "RuntimeError: Internal C++ object already deleted", not just
        # returns a stale value. Both are connected to the same `finished`
        # signal and run in connection order, so this one first is enough.
        worker.finished.connect(self._on_mcp_worker_thread_finished)
        worker.finished.connect(worker.deleteLater)
        self._mcp_worker = worker
        worker.start()
        return True

    def _on_mcp_worker_thread_finished(self) -> None:
        self._mcp_worker = None

    def _on_mcp_discovery_finished(self, server_count: int) -> None:
        self._mcp_server_count = server_count
        if server_count:
            self.chat_log.append_status(f"🔌 Connected {server_count} MCP server(s).")
        if self._mcp_reconnect_callback is not None:
            callback = self._mcp_reconnect_callback
            self._mcp_reconnect_callback = None
            callback(server_count)

    def reconnect_mcp_servers(self, on_done=None) -> bool:
        """Unregisters every current MCP tool, then reconnects from the
        current mcp_servers.json — what ui/mcp_settings.py's "Reconnect
        Now" calls after an add/edit/remove, so changes take effect
        without restarting JARVIS.

        Returns True if a reconnect was actually started, False if a
        discovery/reconnect was already in progress (caller should ask the
        user to wait a moment and try again — `on_done` is NOT called in
        that case, since nothing was actually kicked off)."""
        if self._mcp_worker is not None and self._mcp_worker.isRunning():
            return False

        for tool in list(self.agent.tool_registry.all()):
            if tool.name.startswith("mcp__"):
                self.agent.tool_registry.unregister(tool.name)
        self._mcp_server_count = 0

        self._mcp_reconnect_callback = on_done
        self._start_mcp_discovery()
        return True

    def show_and_focus(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @property
    def voice_available(self) -> bool:
        return self._recorder is not None

    def _open_folders_dialog(self) -> None:
        dialog = FoldersDialog(self)
        dialog.exec()

    def _open_usage_dialog(self) -> None:
        dialog = UsageDialog(str(self.conversation_id), self)
        dialog.exec()

    def _open_mcp_dialog(self) -> None:
        dialog = MCPServersDialog(self, self)
        dialog.exec()

    def _on_reminder_fired(self, reminder: dict) -> None:
        self.notifications.notify(
            "JARVIS Reminder", reminder["title"], reminder_id=reminder["id"]
        )
        self.chat_log.append_status(f"🔔 Reminder: {reminder['title']}")

    # --- UI state management -------------------------------------------------

    def _set_thinking(self, thinking: bool) -> None:
        self.input_field.setEnabled(not thinking)
        self.send_button.setEnabled(not thinking)
        if self._recorder is not None:
            self.mic_button.setEnabled(not thinking)
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
        if state.get("requires_confirmation"):
            self._handle_confirmation(state)
            return
        if state.get("error"):
            self.chat_log.append_message("error", f"Sorry, I ran into a problem: {state['error']}")
        else:
            self.chat_log.append_message("assistant", state.get("response") or "")

    def _on_turn_failed(self, message: str) -> None:
        self._set_thinking(False)
        self.chat_log.append_message("error", f"Unexpected error: {message}")

    # --- Voice (push-to-talk, spec.md §24) -------------------------------------

    def _on_mic_pressed(self) -> None:
        assert self._recorder is not None
        if not self.voice_enabled:
            self.chat_log.append_status("Voice is currently off — enable it from the tray icon.")
            return
        try:
            self._recorder.start()
        except MicrophoneUnavailableError as exc:
            self.chat_log.append_message("error", f"Microphone unavailable: {exc}")
            return
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        self.status_label.setText("Listening...")

    def _on_mic_released(self) -> None:
        assert self._recorder is not None
        audio = self._recorder.stop()
        self.status_label.setText("Transcribing...")

        self._worker = VoiceTurnWorker(
            self.agent, self.conversation_id, audio, self._recorder.sample_rate, speak_reply=True
        )
        self._worker.transcribed.connect(self._on_voice_transcribed)
        self._worker.succeeded.connect(self._on_turn_succeeded)
        self._worker.failed.connect(self._on_voice_failed)
        self._worker.started_speaking.connect(lambda: self.status_label.setText("Speaking..."))
        self._worker.finished_speaking.connect(lambda: self.status_label.setText(""))
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_voice_transcribed(self, text: str) -> None:
        self.chat_log.append_message("user", text)

    def _on_voice_failed(self, message: str) -> None:
        self._set_thinking(False)
        self.chat_log.append_message("error", message)

    # --- Confirmation flow (spec.md §25 "Waiting for confirmation", §28) ------

    def _handle_confirmation(self, state: dict) -> None:
        request = state.get("confirmation_request") or {}
        tool_name = request.get("tool", "this action")
        arguments = request.get("arguments", {})
        reason = request.get("reason", "")
        detail = ", ".join(f"{k}={v}" for k, v in arguments.items())

        self.chat_log.append_status(f"⚠ JARVIS wants to run: {tool_name}({detail})")

        answer = QMessageBox.question(
            self,
            "JARVIS needs confirmation",
            f"{reason}\n\n{tool_name}({detail})\n\nThis cannot be automatically undone. Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        approved = answer == QMessageBox.StandardButton.Yes

        self._set_thinking(True)
        self._worker = ConfirmTurnWorker(
            self.agent, self.conversation_id, tool_name, arguments, approved
        )
        self._worker.succeeded.connect(self._on_turn_succeeded)
        self._worker.failed.connect(self._on_turn_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()


def run(ctx: BootstrapContext, health_results: list | None = None) -> int:
    import sys

    from app.qt_sigint import enable_ctrl_c_quit
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from ui.tray import TrayIcon

    app = QApplication.instance() or QApplication(sys.argv)
    _sigint_timer = enable_ctrl_c_quit(app)  # noqa: F841 - must stay alive until app.exec() returns
    window = ChatWindow(ctx)

    if health_results:
        from app.lifecycle import summarize_health_warnings

        warning = summarize_health_warnings(health_results)
        if warning:
            window.chat_log.append_status(warning)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(window)
        tray.show()
        window.tray = tray
    else:
        logger.info("No system tray available on this platform — running without one.")

    # Always shown on launch now — whether started manually or by
    # app/supervisor.py's hotkey/tray, this process only exists because
    # someone just asked for it, so there's no "start hidden" case anymore.
    window.show()

    return app.exec()

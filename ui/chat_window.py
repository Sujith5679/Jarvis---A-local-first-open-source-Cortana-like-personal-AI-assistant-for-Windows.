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
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSettings, QThread, Signal
from PySide6.QtGui import QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
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

from ui.history import ConversationHistoryDialog
from ui.icon import build_icon, build_icon_pixmap
from ui.messages import ChatLog
from ui.notifications import NotificationService
from ui.settings import FoldersDialog
from ui.theme import (
    SETTINGS_APP,
    SETTINGS_ORG,
    VALID_THEME_MODES,
    load_theme_mode,
    resolve_theme,
    save_theme_mode,
)
from ui.usage_dialog import UsageDialog

_GEOMETRY_SETTINGS_KEY = "ui/chat_window_geometry"

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
                # state.get("response") is guaranteed truthy by should_speak,
                # but we use 'or ""' to satisfy strict type checkers like Pyright.
                audio, sr = await tts_synthesize(state.get("response") or "", session_id=session_id)
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
        # Set by run() below after construction, if a tray is available on
        # this platform — purely a convenience menu (pause indexing,
        # open; the global hotkey now lives entirely in app/supervisor.py.
        import typing
        self.tray: typing.Any = None

        self.setWindowTitle("JARVIS")
        self.setWindowIcon(build_icon())
        # A previous session's saved size/position (see closeEvent) wins if
        # present - makes the popup behave like something docked in place
        # rather than reappearing wherever Windows feels like each launch.
        self.setMinimumSize(300, 400)
        saved_geometry = QSettings(SETTINGS_ORG, SETTINGS_APP).value(_GEOMETRY_SETTINGS_KEY)
        restored = False
        if saved_geometry:
            try:
                import typing
                restored = self.restoreGeometry(typing.cast(bytes, saved_geometry))
            except (TypeError, ValueError):
                # A saved value in an unexpected shape (e.g. a stale/foreign
                # registry entry) should degrade to the default size, never
                # crash startup over a cosmetic preference.
                restored = False
        if not restored:
            self.resize(380, 540)

        self.theme = resolve_theme()
        # No self.menuBar() anywhere below - QMainWindow only creates one
        # lazily on first access, and the compact kebab menu (top_bar,
        # below) replaces what the native menu bar used to hold.

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Compact top bar: title + one kebab menu instead of a permanent
        # native menu bar (spec.md §25 wants this to read as a small chat
        # popup, not a desktop app with its own menu strip). ---
        self.top_bar = QWidget(central)
        top_bar_layout = QHBoxLayout(self.top_bar)
        top_bar_layout.setContentsMargins(10, 6, 6, 6)
        top_bar_layout.setSpacing(6)

        self.logo_label = QLabel(self.top_bar)
        self.logo_label.setPixmap(build_icon_pixmap(20))
        self.logo_label.setFixedSize(20, 20)
        top_bar_layout.addWidget(self.logo_label)

        self.title_label = QLabel("JARVIS", self.top_bar)
        top_bar_layout.addWidget(self.title_label, stretch=1)

        # Presence dot: a small always-visible indicator of what JARVIS is
        # doing right now (idle/listening/thinking/speaking - spec.md §25's
        # required UI states), pulsing while busy. status_label already says
        # this in words; this is the same information read at a glance,
        # closer to how voice assistants like Cortana signal "I'm active"
        # without needing to read anything.
        self.presence_dot = QLabel(self.top_bar)
        self.presence_dot.setFixedSize(9, 9)
        self._presence_opacity = QGraphicsOpacityEffect(self.presence_dot)
        self.presence_dot.setGraphicsEffect(self._presence_opacity)
        self._presence_anim = QPropertyAnimation(self._presence_opacity, b"opacity", self)
        self._presence_anim.setDuration(900)
        self._presence_anim.setStartValue(1.0)
        self._presence_anim.setKeyValueAt(0.5, 0.35)
        self._presence_anim.setEndValue(1.0)
        self._presence_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._presence_anim.setLoopCount(-1)
        top_bar_layout.addWidget(self.presence_dot)

        self.menu_button = QToolButton(self.top_bar)
        self.menu_button.setText("⋮")  # vertical ellipsis
        self.menu_button.setToolTip("Menu")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setMenu(self._build_menu())
        top_bar_layout.addWidget(self.menu_button)
        layout.addWidget(self.top_bar)

        self.chat_log = ChatLog(central, theme=self.theme)
        layout.addWidget(self.chat_log, stretch=1)

        self.status_label = QLabel("", central)
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
            self.mic_button.setFixedSize(34, 34)
            self.mic_button.setToolTip("Hold to talk")
            self.mic_button.pressed.connect(self._on_mic_pressed)
            self.mic_button.released.connect(self._on_mic_released)
            input_layout.addWidget(self.mic_button)

        self.send_button = QPushButton("➤", input_row)
        self.send_button.setFixedSize(34, 34)
        self.send_button.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self.send_button)

        layout.addWidget(input_row)
        self.setCentralWidget(central)
        self._apply_theme_to_chrome()  # also sets the initial (idle) presence dot state

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
        # launches a fresh instance the next time it's needed.
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(_GEOMETRY_SETTINGS_KEY, self.saveGeometry())
        self.scheduler.stop()
        super().closeEvent(event)

    # --- Menu / theme (ui/theme.py) -----------------------------------------

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        new_chat_action = menu.addAction("New Chat")
        new_chat_action.triggered.connect(self.start_new_conversation)
        history_action = menu.addAction("History...")
        history_action.triggered.connect(self._open_history_dialog)

        menu.addSeparator()
        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self._open_folders_dialog)
        usage_action = menu.addAction("Usage && Costs...")
        usage_action.triggered.connect(self._open_usage_dialog)

        menu.addSeparator()
        theme_menu = menu.addMenu("Theme")
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        current_mode = load_theme_mode()
        for mode in VALID_THEME_MODES:
            action = theme_menu.addAction(mode.capitalize())
            action.setCheckable(True)
            action.setChecked(mode == current_mode)
            action.triggered.connect(lambda _checked, m=mode: self._on_theme_selected(m))
            theme_group.addAction(action)
        # Keep a live Python reference - nothing else holds one once
        # _build_menu() returns, and a garbage-collected QActionGroup can
        # take its actions' exclusivity behavior down with it.
        self._theme_action_group = theme_group

        return menu

    def _on_theme_selected(self, mode: str) -> None:
        save_theme_mode(mode)
        self.theme = resolve_theme(mode)
        self._apply_theme_to_chrome()
        self.chat_log.apply_theme(self.theme)
        # Already-rendered bubbles keep the old theme's colors baked into
        # their HTML (see ChatLog.apply_theme's docstring) - re-render the
        # current conversation from storage so switching themes is never
        # half-applied to what's on screen. The opening greeting is never
        # persisted (same as start_new_conversation()/switch_to_conversation()),
        # so an empty result needs the same fallback they use, or switching
        # themes right after startup would wipe it off screen.
        messages = conv_repo.get_messages(self.conversation_id)
        self.chat_log.load_history(messages)
        if not messages:
            self.chat_log.append_message("assistant", "How can I help?")
        # Rebuild the menu so the new mode's checkmark shows next time it opens.
        self.menu_button.setMenu(self._build_menu())

    def _apply_theme_to_chrome(self) -> None:
        """Styles everything except ChatLog (which manages its own
        stylesheet via apply_theme()) - the window background, top bar,
        status line, and input row. Rounded/gradient where QSS actually
        supports it (live-verified: unlike ChatLog's HTML bubbles, plain
        QWidget stylesheets render border-radius and qlineargradient fine),
        in the same cyan/teal family as ui/icon.py's logo."""
        t = self.theme
        self.setStyleSheet(f"QMainWindow {{ background: {t.window_bg}; }}")
        self.top_bar.setStyleSheet(f"background: {t.surface_bg}; border-bottom: none;")
        self.title_label.setStyleSheet(
            f"color: {t.text}; font-weight: 600; font-size: 13px; padding-left: 2px;"
        )
        self.menu_button.setStyleSheet(
            f"QToolButton {{ color: {t.muted_text}; border: none; font-size: 16px; "
            f"border-radius: 4px; padding: 2px 4px; }}"
            f"QToolButton::menu-indicator {{ image: none; }}"
            f"QToolButton:hover {{ background: {t.assistant_bubble_bg}; }}"
        )
        self.status_label.setStyleSheet(
            f"color: {t.status_text}; font-style: italic; padding: 2px 8px; "
            f"background: {t.window_bg};"
        )
        self.input_field.setStyleSheet(
            f"QLineEdit {{ background: {t.input_bg}; color: {t.text}; "
            f"border: 1px solid {t.border}; border-radius: 16px; padding: 6px 12px; }}"
            f"QLineEdit:focus {{ border: 1px solid {t.accent}; }}"
        )
        self.send_button.setStyleSheet(
            f"QPushButton {{ color: #ffffff; border: none; border-radius: 17px; "
            f"font-size: 14px; "
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 {t.accent}, stop:1 {t.accent_end}); }}"
            f"QPushButton:hover {{ background: {t.accent_end}; }}"
            f"QPushButton:disabled {{ background: {t.border}; color: {t.muted_text}; }}"
        )
        if self._recorder is not None and not getattr(self, "_mic_recording", False):
            self.mic_button.setStyleSheet(
                f"QPushButton {{ background: {t.assistant_bubble_bg}; color: {t.text}; "
                f"border: none; border-radius: 17px; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {t.border}; }}"
                f"QPushButton:disabled {{ color: {t.muted_text}; }}"
            )
        # Refresh the presence dot's color for the new theme without
        # changing what state it's actually reporting (pulsing or not).
        self._set_presence(getattr(self, "_presence_state", "idle"))

    # --- Presence dot (top bar) ---------------------------------------------

    _PRESENCE_COLORS = {
        "idle": "muted_text",
        "listening": "error_text",
        "thinking": "accent",
        "speaking": "accent_end",
    }

    def _set_presence(self, state: str) -> None:
        self._presence_state = state
        color = getattr(self.theme, self._PRESENCE_COLORS.get(state, "muted_text"))
        self.presence_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        if state == "idle":
            self._presence_anim.stop()
            self._presence_opacity.setOpacity(1.0)
        elif self._presence_anim.state() != QPropertyAnimation.State.Running:
            self._presence_anim.start()

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

    def _open_history_dialog(self) -> None:
        dialog = ConversationHistoryDialog(self, self)
        dialog.exec()

    # --- Conversation switching (ui/history.py) ----------------------------
    #
    # Both guard against an in-flight worker (a running agent turn): its
    # succeeded/failed signal handlers append to self.chat_log using
    # whatever conversation_id was current when it *finished*, not when it
    # started - switching mid-turn would render a stale reply into a
    # conversation it was never actually part of. Same reasoning as
    # _set_thinking() disabling input during a turn, applied here too.

    def _is_worker_running(self) -> bool:
        if self._worker is None:
            return False
        try:
            return self._worker.isRunning()
        except RuntimeError:
            # The C++ object was already deleted by deleteLater
            self._worker = None
            return False

    def start_new_conversation(self) -> None:
        if self._is_worker_running():
            self.status_label.setText("Please wait for the current response to finish first.")
            return
        self.conversation_id = conv_repo.create_conversation()
        self.chat_log.clear()
        self.chat_log.append_message("assistant", "How can I help?")

    def switch_to_conversation(self, conversation_id: int) -> None:
        if self._is_worker_running():
            self.status_label.setText("Please wait for the current response to finish first.")
            return
        self.conversation_id = conversation_id
        messages = conv_repo.get_messages(conversation_id)
        self.chat_log.load_history(messages)
        if not messages:
            self.chat_log.append_message("assistant", "How can I help?")

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
        self._set_presence("thinking" if thinking else "idle")
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
            self.chat_log.append_message(
                "assistant", state.get("response") or "", state.get("citations")
            )

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
        self._set_presence("listening")
        # Visual "Listening" state (spec.md §25's required UI states) - the
        # mic button otherwise looks identical whether idle or recording.
        self._mic_recording = True
        self.mic_button.setStyleSheet(
            f"background: {self.theme.error_text}; color: white; border: none; "
            f"border-radius: 17px; font-size: 14px;"
        )

    def _on_mic_released(self) -> None:
        assert self._recorder is not None
        audio = self._recorder.stop()
        self._mic_recording = False
        self.mic_button.setStyleSheet("")
        self._apply_theme_to_chrome()  # restore the mic button's idle (non-inline) style
        self.status_label.setText("Transcribing...")
        self._set_presence("thinking")

        self._worker = VoiceTurnWorker(
            self.agent, self.conversation_id, audio, self._recorder.sample_rate, speak_reply=True
        )
        self._worker.transcribed.connect(self._on_voice_transcribed)
        self._worker.succeeded.connect(self._on_turn_succeeded)
        self._worker.failed.connect(self._on_voice_failed)
        self._worker.started_speaking.connect(self._on_speaking_started)
        self._worker.finished_speaking.connect(self._on_speaking_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_voice_transcribed(self, text: str) -> None:
        self.chat_log.append_message("user", text)

    def _on_voice_failed(self, message: str) -> None:
        self._set_thinking(False)
        self.chat_log.append_message("error", message)

    def _on_speaking_started(self) -> None:
        self.status_label.setText("Speaking...")
        self._set_presence("speaking")

    def _on_speaking_finished(self) -> None:
        self.status_label.setText("")
        self._set_presence("idle")

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
    assert isinstance(app, QApplication)
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

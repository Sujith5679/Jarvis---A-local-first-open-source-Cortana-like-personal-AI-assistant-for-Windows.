"""System tray icon (spec.md §25).

Menu exactly per spec:

    Open JARVIS
    Start/Stop voice
    Pause indexing
    Settings
    Reindex files
    View logs
    Quit

The tray icon is JARVIS's app icon (ui/icon.py) - a small procedurally
drawn "AI core" orb, not a raster asset file.

This tray icon only exists while JARVIS's main window is actually running
— it's a convenience menu for that session, not what keeps Ctrl+Space
available (that's app/supervisor.py's separate, always-on tray+hotkey
process). Closing the window (the titlebar X, or this menu's "Quit") fully
exits the process — see ui/chat_window.py's closeEvent.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from rag import indexing_state

from ui.icon import build_icon
from ui.settings import IndexingWorker

logger = logging.getLogger("jarvis.ui.tray")


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, parent=None) -> None:
        super().__init__(build_icon(), parent)
        self.window = window
        self._index_worker: IndexingWorker | None = None
        self.setToolTip("JARVIS")

        menu = QMenu()

        open_action = menu.addAction("Open JARVIS")
        open_action.triggered.connect(self._open)

        self.voice_action = menu.addAction("Start/Stop voice")
        self.voice_action.setCheckable(True)
        self.voice_action.setChecked(window.voice_enabled)
        self.voice_action.setEnabled(window.voice_available)
        if not window.voice_available:
            self.voice_action.setToolTip("Voice is disabled (JARVIS_ENABLE_VOICE=false)")
        self.voice_action.toggled.connect(self._toggle_voice)

        self.indexing_action = menu.addAction("Pause indexing")
        self.indexing_action.setCheckable(True)
        self.indexing_action.toggled.connect(self._toggle_indexing)

        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self._open_settings)

        reindex_action = menu.addAction("Reindex files")
        reindex_action.triggered.connect(self._reindex)

        logs_action = menu.addAction("View logs")
        logs_action.triggered.connect(self._view_logs)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_app)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._open()

    def _open(self) -> None:
        self.window.show_and_focus()

    def _toggle_voice(self, checked: bool) -> None:
        self.window.voice_enabled = checked

    def _toggle_indexing(self, checked: bool) -> None:
        indexing_state.set_paused(checked)
        self.indexing_action.setText("Resume indexing" if checked else "Pause indexing")

    def _open_settings(self) -> None:
        self.window._open_folders_dialog()

    def _reindex(self) -> None:
        if indexing_state.is_paused():
            self.showMessage(
                "JARVIS",
                "Indexing is paused — resume it first.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        if self._index_worker is not None and self._index_worker.isRunning():
            return
        self._index_worker = IndexingWorker()
        self._index_worker.succeeded.connect(self._on_reindex_succeeded)
        self._index_worker.failed.connect(self._on_reindex_failed)
        self._index_worker.finished.connect(self._index_worker.deleteLater)
        self._index_worker.start()
        self.showMessage("JARVIS", "Reindexing started…", QSystemTrayIcon.MessageIcon.Information)

    def _on_reindex_succeeded(self, summary) -> None:
        from tools import file_search

        file_search.invalidate_cache()
        self.showMessage(
            "JARVIS",
            f"Indexed {summary.indexed}, skipped {summary.skipped_unchanged}, "
            f"{summary.failed} failed.",
            QSystemTrayIcon.MessageIcon.Information,
        )

    def _on_reindex_failed(self, message: str) -> None:
        self.showMessage(
            "JARVIS", f"Reindexing failed: {message}", QSystemTrayIcon.MessageIcon.Critical
        )

    def _view_logs(self) -> None:
        logs_dir = self.window.ctx.settings.logs_dir
        try:
            os.startfile(str(logs_dir))  # noqa: S606 - fixed local path, not user input
        except OSError as exc:
            logger.warning("Could not open logs folder: %s", exc)

    def quit_app(self) -> None:
        self.window.close()  # closeEvent always fully exits now
        QApplication.instance().quit()

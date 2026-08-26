"""System tray icon (spec.md §25).

Menu exactly per spec:

    Open JARVIS
    Start/Stop voice
    Pause indexing
    Settings
    Reindex files
    View logs
    Quit

No branded icon asset exists yet, so the tray icon is a small generated
monogram rather than a placeholder image file that would need replacing
later anyway — swap `_build_icon()` for `QIcon("path/to/real/icon.ico")`
once real branding exists.

Closing the main window (the titlebar X) hides it to the tray instead of
exiting — only this menu's "Quit" (or `TrayIcon.quit_app()`) actually ends
the process. See `ui/chat_window.py`'s `closeEvent`/`_really_quit`.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from rag import indexing_state

from ui.settings import IndexingWorker

logger = logging.getLogger("jarvis.ui.tray")


def _build_icon() -> QIcon:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#4f46e5"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI", int(size * 0.5), QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "J")
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, parent=None) -> None:
        super().__init__(_build_icon(), parent)
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
        self.window._really_quit = True
        self.window.close()
        QApplication.instance().quit()

"""Lightweight always-on supervisor: owns the global hotkey and a minimal
tray icon so the full JARVIS app only has to run while it's actually in
use, instead of staying resident (loaded agent/RAG/voice stack, DB
connections, ...) the whole time.

Deliberately imports NONE of agent/llm/rag/voice/tools/storage/scheduler —
only Qt (for the tray icon + event loop), the `keyboard` library (for the
global hotkey, via ui/hotkey.py, itself Qt-only), and config.settings
(lightweight, pydantic-only). That keeps this process's memory footprint a
small fraction of the full app's.

`python -m app.supervisor` (via start_jarvis_supervisor.bat) is what
"Start JARVIS with Windows" (app/windows_startup.py) now registers — the
thing that's actually always running is this, not the full app.

Pressing the hotkey, or clicking "Open JARVIS" in this tray icon:
  - if JARVIS's main window already exists — found via its exact window
    title (ui/chat_window.py's `setWindowTitle("JARVIS")`), via the Win32
    FindWindow API, which matches regardless of whether the window is
    currently visible — brings it to the foreground.
  - otherwise, launches start_jarvis.bat fresh.

Closing JARVIS's own window now fully exits that (heavy) process
(ui/chat_window.py's closeEvent) — this supervisor is the only thing left
running afterward, until the next hotkey press.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time

from config.settings import BASE_DIR, get_settings
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from ui.icon import build_icon

from app.qt_sigint import enable_ctrl_c_quit

logger = logging.getLogger("jarvis.app.supervisor")

WINDOW_TITLE = "JARVIS"
LAUNCHER = BASE_DIR / "start_jarvis.bat"
SW_RESTORE = 9
# Suppresses launching a second instance if the hotkey fires again while a
# previous launch is still starting up (the window doesn't exist for the
# first second or two) — not a hard lock, just a debounce.
RELAUNCH_DEBOUNCE_SECONDS = 8.0

# ui.icon has no dependency beyond PySide6 itself (no ui.settings/rag import
# chain), so importing it directly here - unlike ui.tray, which would pull
# in ui.settings -> rag.embeddings/rag.ingestion - keeps this process light
# (measured ~3.3MB vs. the full app's 100-200MB+, see module docstring).


def find_main_window() -> int:
    """Returns JARVIS's main window HWND if it's running, 0 if not."""
    return ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)


def bring_to_foreground(hwnd: int) -> None:
    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
    ctypes.windll.user32.SetForegroundWindow(hwnd)


class Supervisor:
    def __init__(self) -> None:
        # None, not 0.0: time.monotonic()'s epoch is arbitrary (not "time
        # since 0"), so 0.0 isn't a safe "never launched" sentinel — an
        # explicit None avoids ever mis-debouncing the very first trigger.
        self._last_launch: float | None = None

    def open_or_focus(self) -> None:
        hwnd = find_main_window()
        if hwnd:
            bring_to_foreground(hwnd)
            return

        if (
            self._last_launch is not None
            and time.monotonic() - self._last_launch < RELAUNCH_DEBOUNCE_SECONDS
        ):
            logger.info("JARVIS is still starting up — ignoring repeated trigger.")
            return

        if not LAUNCHER.exists():
            logger.warning("Launcher not found: %s", LAUNCHER)
            return

        try:
            # cmd /c rather than shell=True: runs the fixed local .bat path
            # without invoking a shell over any string we built ourselves.
            subprocess.Popen(  # noqa: S603, S607 - fixed local path, no user input
                ["cmd", "/c", str(LAUNCHER)], cwd=str(BASE_DIR)
            )
        except OSError as exc:
            logger.warning("Could not launch JARVIS: %s", exc)
            return
        self._last_launch = time.monotonic()
        logger.info("Launched JARVIS (%s)", LAUNCHER)


def main() -> int:
    app = QApplication(sys.argv)
    _sigint_timer = enable_ctrl_c_quit(app)  # noqa: F841 - must stay alive until app.exec() returns
    # This tray icon *is* the app, in the Qt sense — there's never a
    # top-level QWidget window here for Qt to auto-quit on.
    app.setQuitOnLastWindowClosed(False)

    supervisor = Supervisor()

    tray = QSystemTrayIcon(build_icon())
    tray.setToolTip("JARVIS (idle — press the hotkey or click to open)")

    menu = QMenu()
    open_action = menu.addAction("Open JARVIS")
    open_action.triggered.connect(supervisor.open_or_focus)
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    tray.setContextMenu(menu)

    def _on_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            supervisor.open_or_focus()

    tray.activated.connect(_on_activated)
    tray.show()

    from ui.hotkey import GlobalHotkey

    settings = get_settings()
    hotkey = GlobalHotkey(settings.jarvis_hotkey)
    hotkey.bridge.triggered.connect(supervisor.open_or_focus)
    hotkey.register()

    try:
        return app.exec()
    finally:
        hotkey.unregister()


if __name__ == "__main__":
    sys.exit(main())

"""Minimal UI shell (Phase 0).

Proves the desktop UI process boots correctly. The real floating chat popup
(`ui/chat_window.py`), system tray (`ui/tray.py`), and global hotkey arrive in
Phases 1 and 6. This module intentionally does nothing more than open a
window so Phase 0 has an end-to-end, runnable demo.
"""

from __future__ import annotations

import sys

from app.bootstrap import BootstrapContext
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget


class JarvisShellWindow(QMainWindow):
    def __init__(self, ctx: BootstrapContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("JARVIS")
        self.resize(360, 480)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        label = QLabel(
            "JARVIS core is running.\n\n"
            f"Data dir: {ctx.settings.data_dir}\n"
            "Chat UI arrives in Phase 1.",
            central,
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.setCentralWidget(central)


def run(ctx: BootstrapContext) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = JarvisShellWindow(ctx)
    window.show()
    return app.exec()

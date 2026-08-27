"""Makes Ctrl+C in a terminal actually stop a running QApplication.

Qt's C++ event loop (`QApplication.exec()`) doesn't hand control back to
the Python interpreter on any predictable schedule, so Python never gets a
chance to notice a delivered SIGINT until *something* runs Python bytecode
again — without this, Ctrl+C in a terminal running `python -m app.main`
(or `app.supervisor`) does nothing, often for a very long time or
effectively forever. Standard, well-known fix for this exact PySide6/Qt
limitation: install a real Python SIGINT handler, plus a harmless
periodic QTimer whose only job is to give the interpreter a moment to run
and notice the pending signal.
"""

from __future__ import annotations

import signal

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

_TICK_INTERVAL_MS = 200


def enable_ctrl_c_quit(app: QApplication) -> QTimer:
    """Call once, right after constructing the QApplication. Returns the
    QTimer — callers MUST keep a reference to it alive for the duration of
    `app.exec()` (e.g. as a local in the same function), or Qt/Python will
    garbage-collect it and Ctrl+C will silently stop working again."""
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(_TICK_INTERVAL_MS)
    return timer

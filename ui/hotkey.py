"""Global hotkey (spec.md §26) — opens/focuses the popup from anywhere.

Uses the `keyboard` library's global low-level hook. Its callback runs on
`keyboard`'s own background listener thread, not the Qt UI thread — Qt
widgets are not thread-safe to touch directly from there (same rule
scheduler/service.py's ReminderBridge follows), so the callback only emits
a Qt signal (`QObject.emit()` is safe cross-thread) and the actual
show/focus work happens in whatever slot the UI connects on the GUI thread.

Registration is best-effort: it can fail for reasons outside JARVIS's
control (another app already owns the combo, a restrictive permission
context, ...). Per spec.md §32 that must degrade gracefully — `register()`
logs a warning and returns False rather than raising, so a hotkey failure
never prevents the rest of the app from working.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("jarvis.ui.hotkey")


class HotkeyBridge(QObject):
    triggered = Signal()


class GlobalHotkey:
    def __init__(self, combo: str) -> None:
        self.combo = combo
        self.bridge = HotkeyBridge()
        self._handle = None

    def register(self) -> bool:
        try:
            import keyboard

            self._handle = keyboard.add_hotkey(self.combo, self.bridge.triggered.emit)
        except Exception as exc:
            logger.warning(
                "Could not register global hotkey %r — JARVIS still works, just not via "
                "hotkey. (%s)",
                self.combo,
                exc,
            )
            return False
        logger.info("Registered global hotkey: %s", self.combo)
        return True

    def unregister(self) -> None:
        if self._handle is None:
            return
        try:
            import keyboard

            keyboard.remove_hotkey(self._handle)
        except Exception:
            logger.debug("Hotkey unregister failed (already gone?)", exc_info=True)
        finally:
            self._handle = None

"""Runtime "pause indexing" toggle (spec.md §25's tray menu item).

A simple in-process flag, not persisted — it resets to "not paused" on every
restart, same as the tray's "Start/Stop voice" toggle. `ui/settings.py`'s
`IndexingWorker` checks this before running a sync; `ui/tray.py`'s "Pause
indexing" menu item flips it.
"""

from __future__ import annotations

_paused = False


def is_paused() -> bool:
    return _paused


def set_paused(paused: bool) -> None:
    global _paused
    _paused = paused

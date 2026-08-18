"""Miscellaneous background jobs (spec.md §43): DB maintenance, cache cleanup.

Reminder checking is significant enough to get its own module
(scheduler/reminders.py); this one is for the smaller periodic housekeeping
jobs. Only DB maintenance exists so far — cache cleanup arrives with Phase 4
(web-fetch caching, spec.md §44).
"""

from __future__ import annotations

import logging

from storage.database import connect

logger = logging.getLogger("jarvis.scheduler.jobs")


def run_database_maintenance() -> None:
    """SQLite's own `PRAGMA optimize` (cheap, safe to run periodically) —
    updates query planner statistics so retrieval/list queries stay fast as
    the database grows."""
    try:
        conn = connect()
        try:
            conn.execute("PRAGMA optimize")
        finally:
            conn.close()
    except Exception:
        logger.exception("Database maintenance job failed")

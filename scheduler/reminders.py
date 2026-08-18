"""Reminder due-check, run by the scheduler on its background thread.

Never touches UI directly — returns the reminders that just fired so the
caller can hand them to the GUI thread (Qt widgets aren't thread-safe; see
scheduler/service.py's ReminderBridge).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from security.audit import log_event
from storage.repositories import reminders as reminders_repo

logger = logging.getLogger("jarvis.scheduler.reminders")


def check_and_fire_due_reminders() -> list[dict]:
    now = datetime.now(UTC)
    try:
        fired = reminders_repo.fire_due_reminders(now)
    except Exception:
        logger.exception("Reminder due-check failed")
        return []

    for reminder in fired:
        log_event(
            "reminder_fired",
            status="success",
            input_summary=reminder["title"],
            result_summary=f"trigger_at={reminder['trigger_at']}",
        )
    return fired

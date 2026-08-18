"""Reminder persistence + firing logic (spec.md §22).

`fire_due_reminders()` is the one piece of business logic in this module
(everything else is plain CRUD): it finds pending reminders whose trigger
time has passed, marks them fired, and — for recurring reminders — advances
`trigger_at` to the next occurrence and leaves them `pending` again rather
than creating a duplicate row. It's written to be safe to call repeatedly
(e.g. on a poll interval and again at startup to recover missed reminders)
since a reminder is only ever returned/fired once per due occurrence.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from storage.database import get_connection

VALID_RECURRENCES = ("daily", "weekly")
RECURRENCE_INTERVALS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}


def create_reminder(
    *,
    title: str,
    trigger_at: str,
    description: str | None = None,
    recurrence: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    if recurrence is not None and recurrence not in VALID_RECURRENCES:
        raise ValueError(f"Invalid recurrence: {recurrence!r}")
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            """INSERT INTO reminders
                   (title, description, trigger_at, recurrence, status, created_at, completed_at)
               VALUES (?, ?, ?, ?, 'pending', ?, NULL)""",
            (title, description, trigger_at, recurrence, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_reminder(reminder_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_reminders(
    status: str | None = None, conn: sqlite3.Connection | None = None
) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        if status:
            rows = c.execute(
                "SELECT * FROM reminders WHERE status = ? ORDER BY trigger_at", (status,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM reminders ORDER BY trigger_at").fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def complete_reminder(reminder_id: int, conn: sqlite3.Connection | None = None) -> bool:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute(
            "UPDATE reminders SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, reminder_id),
        )
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def dismiss_reminder(reminder_id: int, conn: sqlite3.Connection | None = None) -> bool:
    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute(
            "UPDATE reminders SET status = 'dismissed' WHERE id = ?", (reminder_id,)
        )
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_due_reminders(now_iso: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Read-only: pending reminders whose trigger_at has passed. Does not
    change their status — see fire_due_reminders() for that."""

    def _run(c: sqlite3.Connection) -> list[dict]:
        rows = c.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND trigger_at <= ? "
            "ORDER BY trigger_at",
            (now_iso,),
        ).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def fire_due_reminders(now: datetime, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Finds due pending reminders and fires each exactly once:
    - one-off: status -> 'fired'.
    - recurring: trigger_at advances to the next occurrence, stays 'pending'
      (so it's never returned twice for the same occurrence, and comes due
      again naturally later).

    Returns the reminders as they were *before* the update (so callers see
    the trigger_at that just fired, not the next one).
    """
    now_iso = now.isoformat()

    def _run(c: sqlite3.Connection) -> list[dict]:
        due = get_due_reminders(now_iso, conn=c)
        for reminder in due:
            if reminder["recurrence"] in RECURRENCE_INTERVALS:
                interval = RECURRENCE_INTERVALS[reminder["recurrence"]]
                next_trigger = datetime.fromisoformat(reminder["trigger_at"]) + interval
                # Guard against a long-offline gap causing an immediate re-fire loop.
                while next_trigger <= now:
                    next_trigger += interval
                c.execute(
                    "UPDATE reminders SET trigger_at = ? WHERE id = ?",
                    (next_trigger.isoformat(), reminder["id"]),
                )
            else:
                c.execute(
                    "UPDATE reminders SET status = 'fired' WHERE id = ?", (reminder["id"],)
                )
        return due

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

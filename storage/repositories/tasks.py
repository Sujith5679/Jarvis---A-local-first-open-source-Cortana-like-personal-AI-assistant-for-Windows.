"""Task persistence (spec.md §21)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from storage.database import get_connection

VALID_STATUSES = ("open", "in_progress", "completed", "cancelled")
VALID_PRIORITIES = ("low", "normal", "high")


def create_task(
    *,
    title: str,
    description: str | None = None,
    priority: str = "normal",
    due_at: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"Invalid priority: {priority!r}")
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            """INSERT INTO tasks
                   (title, description, status, priority, due_at,
                    created_at, updated_at, completed_at)
               VALUES (?, ?, 'open', ?, ?, ?, ?, NULL)""",
            (title, description, priority, due_at, now, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_task(task_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_tasks(status: str | None = None, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        if status:
            rows = c.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY due_at IS NULL, due_at, created_at",
                (status,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM tasks ORDER BY status, due_at IS NULL, due_at, created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def update_task(
    task_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    status: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    if priority is not None and priority not in VALID_PRIORITIES:
        raise ValueError(f"Invalid priority: {priority!r}")
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}")
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> bool:
        existing = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            return False
        c.execute(
            """UPDATE tasks SET
                   title = ?, description = ?, priority = ?, due_at = ?, status = ?, updated_at = ?
               WHERE id = ?""",
            (
                title if title is not None else existing["title"],
                description if description is not None else existing["description"],
                priority if priority is not None else existing["priority"],
                due_at if due_at is not None else existing["due_at"],
                status if status is not None else existing["status"],
                now,
                task_id,
            ),
        )
        return True

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def complete_task(task_id: int, conn: sqlite3.Connection | None = None) -> bool:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute(
            "UPDATE tasks SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, task_id),
        )
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_task(task_id: int, conn: sqlite3.Connection | None = None) -> bool:
    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

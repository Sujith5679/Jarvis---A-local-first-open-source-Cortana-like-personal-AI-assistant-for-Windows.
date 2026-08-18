"""Note persistence (spec.md §20).

Search is a simple SQL LIKE over title/content for V1 — spec explicitly
marks vector-store embedding of notes as *optional*; add it later by having
rag/ingestion embed rows from this table the same way it embeds document
chunks, without changing this module's interface.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from storage.database import get_connection


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
    d["archived"] = bool(d["archived"])
    return d


def create_note(
    *,
    title: str | None,
    content: str,
    tags: list[str] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    now = datetime.now(UTC).isoformat()
    tags_json = json.dumps(tags or [])

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            "INSERT INTO notes (title, content, tags, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (title, content, tags_json, now, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_note(note_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def search_notes(
    query: str, *, include_archived: bool = False, conn: sqlite3.Connection | None = None
) -> list[dict]:
    like = f"%{query}%"
    sql = "SELECT * FROM notes WHERE (title LIKE ? OR content LIKE ?)"
    params: list = [like, like]
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY updated_at DESC"

    def _run(c: sqlite3.Connection) -> list[dict]:
        rows = c.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_notes(
    *, include_archived: bool = False, conn: sqlite3.Connection | None = None
) -> list[dict]:
    sql = "SELECT * FROM notes"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY updated_at DESC"

    def _run(c: sqlite3.Connection) -> list[dict]:
        return [_row_to_dict(r) for r in c.execute(sql).fetchall()]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def update_note(
    note_id: int,
    *,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> bool:
        existing = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not existing:
            return False
        new_title = title if title is not None else existing["title"]
        new_content = content if content is not None else existing["content"]
        new_tags = json.dumps(tags) if tags is not None else existing["tags"]
        c.execute(
            "UPDATE notes SET title = ?, content = ?, tags = ?, updated_at = ? WHERE id = ?",
            (new_title, new_content, new_tags, now, note_id),
        )
        return True

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def archive_note(note_id: int, conn: sqlite3.Connection | None = None) -> bool:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute(
            "UPDATE notes SET archived = 1, updated_at = ? WHERE id = ?", (now, note_id)
        )
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_note(note_id: int, conn: sqlite3.Connection | None = None) -> bool:
    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

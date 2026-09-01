"""Conversation/message persistence — spec.md §36 (`conversations`, `messages`).

This is JARVIS's "working memory" store (spec.md §30): the raw turn history
a single conversation is built from. Cross-conversation persistent memory
(preferences/knowledge that carry into *other* conversations) is a
separate concern — storage/repositories/memories.py.

Every conversation is titled from its first user message (see
`_maybe_set_title`) so ui/history.py's conversation list has something more
useful to show than a timestamp — same idea as most chat apps' auto-named
threads. `set_title` exists for an explicit override if that's ever wanted
(not currently exposed as an agent tool or UI action — title is purely a
display convenience, users manage per-conversation content by switching to
it, not by renaming it).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from config.defaults import DEFAULT_CONVERSATION_TITLE_MAX_CHARS

from storage.database import get_connection


def create_conversation(title: str | None = None, conn: sqlite3.Connection | None = None) -> int:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def _maybe_set_title(c: sqlite3.Connection, conversation_id: int, content: str) -> None:
    """Auto-titles a conversation from its first user message, once. A
    no-op if it already has a title (explicit, via set_title(), or from an
    earlier first message — this only ever fires the very first time)."""
    row = c.execute(
        "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    if row is None or row["title"]:
        return
    title = " ".join(content.split())[:DEFAULT_CONVERSATION_TITLE_MAX_CHARS].strip()
    if title:
        c.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))


def set_title(
    conversation_id: int, title: str, conn: sqlite3.Connection | None = None
) -> None:
    def _run(c: sqlite3.Connection) -> None:
        c.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))

    if conn is not None:
        _run(conn)
        return
    with get_connection() as c:
        _run(c)


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    *,
    tool_calls: list[dict] | None = None,
    citations: list[dict] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    if role not in ("user", "assistant", "system", "tool"):
        raise ValueError(f"Invalid message role: {role!r}")

    now = datetime.now(UTC).isoformat()
    tool_calls_json = json.dumps(tool_calls) if tool_calls else None
    citations_json = json.dumps(citations) if citations else None

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            """INSERT INTO messages
               (conversation_id, role, content, tool_calls, citations, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conversation_id, role, content, tool_calls_json, citations_json, now),
        )
        c.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        if role == "user":
            _maybe_set_title(c, conversation_id, content)
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_messages(
    conversation_id: int,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Return messages oldest-first, optionally capped to the most recent `limit`."""

    def _run(c: sqlite3.Connection) -> list[dict]:
        if limit is not None:
            rows = c.execute(
                """SELECT * FROM (
                       SELECT * FROM messages WHERE conversation_id = ?
                       ORDER BY id DESC LIMIT ?
                   ) ORDER BY id ASC""",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_conversations(conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        rows = c.execute("SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_conversation(
    conversation_id: int, conn: sqlite3.Connection | None = None
) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_conversation(conversation_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """Also deletes the conversation's messages — `messages.conversation_id`
    has ON DELETE CASCADE (storage/migrations.py), enforced because
    storage/database.py turns PRAGMA foreign_keys on for every connection."""

    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def to_llm_messages(messages: list[dict]) -> list[dict]:
    """Convert stored rows into the plain {role, content} shape LLM providers expect."""
    return [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "tool"]

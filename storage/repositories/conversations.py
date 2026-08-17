"""Conversation/message persistence — spec.md §36 (`conversations`, `messages`).

This is JARVIS's "working memory" store for Phase 1: the raw turn history a
conversation is built from. The richer memory split (working/episodic/
preference/knowledge, spec.md §30) arrives in Phase 7/V2; for now a
conversation's message history *is* its working memory.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from storage.database import get_connection


def create_conversation(title: str | None = None, conn: sqlite3.Connection | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()

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

    now = datetime.now(timezone.utc).isoformat()
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


def to_llm_messages(messages: list[dict]) -> list[dict]:
    """Convert stored rows into the plain {role, content} shape LLM providers expect."""
    return [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "tool"]

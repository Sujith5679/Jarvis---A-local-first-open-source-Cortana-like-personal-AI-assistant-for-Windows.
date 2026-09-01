"""Persistent cross-conversation memory (spec.md §30, `memories` table).

Deliberately separate from `messages`/`conversations` (working memory,
scoped to one conversation — storage/repositories/conversations.py) — a
*memory* here is a durable fact meant to carry into **future, unrelated**
conversations (e.g. "the user prefers metric units"), injected into every
turn's system prompt by agent/prompts.py's build_system_prompt().

spec.md §30 is explicit and this module's only caller (tools/memory.py)
honors it: "Do not automatically convert every conversation into permanent
memory. Only store permanent memories when: User explicitly asks JARVIS to
remember something..." — nothing here ever creates a memory except in
direct response to a `remember_fact` tool call the LLM made because the
user asked for it; no passive/automatic extraction happens anywhere.
Also per spec.md §30: "The user must be able to inspect and delete
memories" — `recall_facts`/`forget_fact` (tools/memory.py) are that
inspect/delete path, conversational rather than a settings UI, matching
how notes/tasks/reminders are already managed only through chat in this
app.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from storage.database import get_connection

# spec.md §30's four memory kinds. Only "preference" and "knowledge" are
# ever written here in practice — "working" memory is the messages table
# itself, and "episodic" is reserved for a future summarization feature
# (spec.md's own V2 roadmap), not built yet.
VALID_MEMORY_TYPES = ("working", "episodic", "preference", "knowledge")
DEFAULT_MEMORY_TYPE = "knowledge"


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
    d["deletable"] = bool(d["deletable"])
    return d


def create_memory(
    content: str,
    *,
    memory_type: str = DEFAULT_MEMORY_TYPE,
    metadata: dict | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"Invalid memory_type: {memory_type!r}")
    now = datetime.now(UTC).isoformat()
    metadata_json = json.dumps(metadata) if metadata else None

    def _run(c: sqlite3.Connection) -> int:
        cur = c.execute(
            "INSERT INTO memories (memory_type, content, metadata, created_at, deletable) "
            "VALUES (?, ?, ?, ?, 1)",
            (memory_type, content, metadata_json, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_memories(
    *,
    memory_type: str | None = None,
    limit: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Most recent first. `limit` bounds both the manual `recall_facts` tool
    result and (via agent/prompts.py) how many get injected into a turn."""
    sql = "SELECT * FROM memories"
    params: list = []
    if memory_type is not None:
        sql += " WHERE memory_type = ?"
        params.append(memory_type)
    sql += " ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    def _run(c: sqlite3.Connection) -> list[dict]:
        return [_row_to_dict(r) for r in c.execute(sql, params).fetchall()]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def search_memories(query: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    like = f"%{query}%"

    def _run(c: sqlite3.Connection) -> list[dict]:
        rows = c.execute(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY created_at DESC", (like,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def get_memory(memory_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return _row_to_dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_memory(memory_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """False both when the id doesn't exist and when it exists but isn't
    deletable — deletable=0 is reserved for a future non-user-facing
    system memory, not used by anything yet, but forget_fact must never be
    able to remove one if it ever is."""

    def _run(c: sqlite3.Connection) -> bool:
        cur = c.execute("DELETE FROM memories WHERE id = ? AND deletable = 1", (memory_id,))
        return cur.rowcount > 0

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

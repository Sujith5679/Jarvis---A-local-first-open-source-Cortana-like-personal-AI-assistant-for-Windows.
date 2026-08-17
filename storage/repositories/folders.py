"""Indexed-folder configuration (spec.md §14.1).

The user explicitly opts folders in; JARVIS never indexes an entire drive by
default. Default candidates (Desktop/Documents/Downloads) are only
*suggested* — nothing here auto-adds them without the caller (UI/CLI) doing
so explicitly.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from storage.database import get_connection


def add_folder(path: str, conn: sqlite3.Connection | None = None) -> int:
    """Register a folder for indexing. Idempotent: re-adding an existing,
    disabled folder re-enables it instead of erroring."""
    normalized = str(Path(path).resolve())
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> int:
        existing = c.execute(
            "SELECT id FROM indexed_folders WHERE path = ?", (normalized,)
        ).fetchone()
        if existing:
            c.execute(
                "UPDATE indexed_folders SET enabled = 1 WHERE id = ?", (existing["id"],)
            )
            return int(existing["id"])
        cur = c.execute(
            "INSERT INTO indexed_folders (path, enabled, added_at) VALUES (?, 1, ?)",
            (normalized, now),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def remove_folder(folder_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Disable a folder. Its already-indexed documents are left in place
    (marked via a later reindex/cleanup pass) rather than deleted here —
    removal of derived data is a separate, explicit lifecycle action
    (spec.md §37)."""

    def _run(c: sqlite3.Connection) -> None:
        c.execute("UPDATE indexed_folders SET enabled = 0 WHERE id = ?", (folder_id,))

    if conn is not None:
        _run(conn)
        return
    with get_connection() as c:
        _run(c)


def list_folders(enabled_only: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        if enabled_only:
            rows = c.execute(
                "SELECT * FROM indexed_folders WHERE enabled = 1 ORDER BY path"
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM indexed_folders ORDER BY path").fetchall()
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def is_path_within_indexed_folders(path: str, conn: sqlite3.Connection | None = None) -> bool:
    """Security check for tools/file_reader.py (spec.md §19, §38): a path is
    only readable if it resolves inside a currently-enabled indexed folder.
    Resolves symlinks/`..` before comparing so traversal can't escape the
    allowlist."""
    try:
        resolved = Path(path).resolve(strict=False)
    except (OSError, ValueError):
        return False

    for folder in list_folders(enabled_only=True, conn=conn):
        folder_path = Path(folder["path"])
        try:
            resolved.relative_to(folder_path)
            return True
        except ValueError:
            continue
    return False

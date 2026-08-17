"""SQLite connection factory.

Single source of truth for opening the local database. Every repository and
service should get its connection from here rather than calling
`sqlite3.connect` directly, so pragmas (foreign keys, WAL mode) and the
database path stay consistent everywhere.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.settings import get_settings


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a new connection to the JARVIS database, fully configured."""
    path = db_path or get_settings().db_path
    conn = sqlite3.connect(str(path))
    _configure(conn)
    return conn


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context-managed connection: commits on success, rolls back on error."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

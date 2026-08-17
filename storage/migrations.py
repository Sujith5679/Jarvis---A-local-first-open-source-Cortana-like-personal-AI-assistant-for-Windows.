"""Forward-only SQLite migration runner.

Every schema change is a new numbered entry in `MIGRATIONS`, never a hand
edit of an already-applied one (spec.md §61.12: "Add migrations whenever the
database schema changes."). Applied versions are tracked in
`schema_migrations` so `apply_migrations()` is idempotent and safe to call on
every startup.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

# Each entry: (version, name, sql). SQL may contain multiple statements.
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial_schema",
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            timezone TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL,
            tool_calls TEXT,
            citations TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

        CREATE TABLE IF NOT EXISTS indexed_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id INTEGER REFERENCES indexed_folders(id) ON DELETE SET NULL,
            path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content_hash TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'indexed', 'failed', 'unsupported')),
            error_message TEXT,
            modified_at TEXT,
            indexed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            page INTEGER,
            section TEXT,
            vector_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
            text,
            content='document_chunks',
            content_rowid='id'
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT NOT NULL,
            tags TEXT,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'completed', 'cancelled')),
            priority TEXT NOT NULL DEFAULT 'normal'
                CHECK (priority IN ('low', 'normal', 'high')),
            due_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            trigger_at TEXT NOT NULL,
            recurrence TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'fired', 'dismissed', 'completed')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders(trigger_at, status);

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL
                CHECK (memory_type IN ('working', 'episodic', 'preference', 'knowledge')),
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            deletable INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT,
            action TEXT NOT NULL,
            tool TEXT,
            status TEXT NOT NULL,
            risk_level TEXT,
            input_summary TEXT,
            result_summary TEXT,
            error_code TEXT,
            duration_ms INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        """,
    ),
    (
        2,
        "fts_sync_triggers",
        """
        -- document_chunks_fts is an external-content FTS5 table (spec.md §16),
        -- so SQLite does not keep it in sync automatically. These triggers
        -- mirror every insert/update/delete on document_chunks into the index.
        CREATE TRIGGER IF NOT EXISTS document_chunks_ai AFTER INSERT ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;

        CREATE TRIGGER IF NOT EXISTS document_chunks_ad AFTER DELETE ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(document_chunks_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
        END;

        CREATE TRIGGER IF NOT EXISTS document_chunks_au AFTER UPDATE ON document_chunks BEGIN
            INSERT INTO document_chunks_fts(document_chunks_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            INSERT INTO document_chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        """,
    ),
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_migrations_table(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] or 0


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration newer than the current schema version.

    Returns the list of version numbers that were applied (empty if the
    schema was already up to date). Safe to call on every startup.
    """
    _ensure_migrations_table(conn)
    applied: list[int] = []
    version = current_version(conn)

    for migration_version, name, sql in sorted(MIGRATIONS, key=lambda m: m[0]):
        if migration_version <= version:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration_version, name, datetime.now(UTC).isoformat()),
        )
        applied.append(migration_version)

    conn.commit()
    return applied

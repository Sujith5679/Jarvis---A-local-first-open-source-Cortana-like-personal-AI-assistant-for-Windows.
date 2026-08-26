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
    (
        3,
        "llm_usage",
        """
        -- One row per LLM call (llm/manager.py), for the "Usage & Costs"
        -- dialog (ui/usage_dialog.py). session_id matches audit_log's
        -- convention: the conversation id, since each app launch creates a
        -- new conversation. estimated_cost_usd is NULL whenever the
        -- provider/model has no known per-token price (llm/pricing.py) -
        -- e.g. Ollama Cloud's flat GPU-time subscription - never a
        -- fabricated 0 or guessed figure.
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL
        );
        CREATE INDEX IF NOT EXISTS idx_llm_usage_session ON llm_usage(session_id);
        CREATE INDEX IF NOT EXISTS idx_llm_usage_timestamp ON llm_usage(timestamp);
        """,
    ),
    (
        4,
        "voice_usage",
        """
        -- One row per STT/TTS call (voice/stt.py, voice/tts.py), the audio
        -- counterpart to llm_usage. STT is billed by audio duration (seconds);
        -- TTS is billed by input character count, not output audio duration -
        -- so `quantity`'s meaning depends on `kind` (see `unit`). Local calls
        -- (faster-whisper/Piper) are real, known $0.00, unlike Ollama Cloud's
        -- *unknown* chat pricing in llm_usage - so estimated_cost_usd is only
        -- ever NULL here for a cloud provider/model voice/pricing.py doesn't
        -- recognize, never for "local".
        CREATE TABLE IF NOT EXISTS voice_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('stt', 'tts')),
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL CHECK (unit IN ('audio_seconds', 'characters')),
            estimated_cost_usd REAL
        );
        CREATE INDEX IF NOT EXISTS idx_voice_usage_session ON voice_usage(session_id);
        CREATE INDEX IF NOT EXISTS idx_voice_usage_timestamp ON voice_usage(timestamp);
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

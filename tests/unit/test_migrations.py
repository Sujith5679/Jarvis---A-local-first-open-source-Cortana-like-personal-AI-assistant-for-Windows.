from __future__ import annotations

import sqlite3

from storage.migrations import MIGRATIONS, apply_migrations, current_version

EXPECTED_TABLES = {
    "users", "settings", "conversations", "messages", "indexed_folders",
    "documents", "document_chunks", "notes", "tasks", "reminders",
    "memories", "events", "audit_log", "schema_migrations",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_apply_migrations_creates_all_tables(migrated_conn):
    tables = _table_names(migrated_conn)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables: {missing}"


def test_apply_migrations_is_idempotent(migrated_conn):
    assert current_version(migrated_conn) == max(v for v, _, _ in MIGRATIONS)
    second_run = apply_migrations(migrated_conn)
    assert second_run == []


def test_fts5_table_present(migrated_conn):
    tables = _table_names(migrated_conn)
    assert "document_chunks_fts" in tables


def test_can_insert_and_read_note(migrated_conn):
    migrated_conn.execute(
        "INSERT INTO notes (title, content, created_at, updated_at) "
        "VALUES (?, ?, datetime('now'), datetime('now'))",
        ("Test note", "Some content"),
    )
    migrated_conn.commit()
    row = migrated_conn.execute("SELECT * FROM notes").fetchone()
    assert row["title"] == "Test note"

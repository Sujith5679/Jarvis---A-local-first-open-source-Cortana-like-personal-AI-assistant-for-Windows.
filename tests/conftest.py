from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from config.settings import get_settings
from storage.migrations import apply_migrations


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Settings instance pointed at a throwaway data dir, not the real one.

    Also chdir's into tmp_path so pydantic-settings' `env_file=".env"` lookup
    can't find (and silently load) the real repo `.env` — otherwise tests run
    against whatever real credentials happen to be configured locally.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()


@pytest.fixture
def migrated_conn():
    """An in-memory SQLite connection with all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def real_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real (file-based) migrated database at settings.db_path, for code that
    goes through storage.database.get_connection() (repositories, audit, agent).

    Also chdir's into tmp_path so the real repo `.env` can't be picked up
    (see isolated_settings for why that matters).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()

    from storage.database import connect

    conn = connect(settings.db_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()

    yield settings
    get_settings.cache_clear()

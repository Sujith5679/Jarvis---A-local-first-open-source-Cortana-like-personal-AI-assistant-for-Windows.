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


@pytest.fixture
def indexed_sample_folder(real_db):
    """A real indexed folder with a couple of small text files, already run
    through the full ingestion pipeline (real local embeddings + a real,
    test-scoped FAISS index). Yields (folder_dict, pipeline, file_paths).

    Also clears `tools.file_search`'s cached retriever singleton before and
    after, since that cache holds a VectorStore bound to whatever
    settings.indexes_dir was active when it was first built — without this,
    it would leak a stale path across tests that each get their own tmp_path.
    """
    from rag.embeddings import get_default_embedding_provider
    from rag.ingestion import IngestionPipeline
    from rag.vector_store import get_default_vector_store
    from storage.repositories import folders as folders_repo
    from tools import file_search

    file_search._get_retriever.cache_clear()

    folder_dir = real_db.data_dir / "sample_source_folder"
    folder_dir.mkdir(parents=True, exist_ok=True)

    claims_file = folder_dir / "claimsx_report.txt"
    claims_file.write_text(
        "ClaimsX Evaluation Report\n\n"
        "The ClaimsX project evaluated a fraud detection approach for insurance "
        "claims using gradient boosted trees on transaction features. The main "
        "fraud detection approach combined feature engineering with an XGBoost "
        "classifier and achieved strong precision on held-out data.\n",
        encoding="utf-8",
    )

    notes_file = folder_dir / "notes.md"
    notes_file.write_text(
        "# Weekend Notes\n\nRemember to buy groceries and water the plants.\n",
        encoding="utf-8",
    )

    folder_id = folders_repo.add_folder(str(folder_dir))
    folder = folders_repo.list_folders(enabled_only=True)[0]
    assert folder["id"] == folder_id

    embedding_provider = get_default_embedding_provider()
    vector_store = get_default_vector_store(dimension=embedding_provider.dimension)
    pipeline = IngestionPipeline(embedding_provider=embedding_provider, vector_store=vector_store)
    pipeline.sync_all_enabled_folders()

    yield folder, pipeline, {"claims": claims_file, "notes": notes_file}

    file_search._get_retriever.cache_clear()

from __future__ import annotations

import pytest
from security.audit import audit_action, log_event


def test_log_event_writes_row(migrated_conn):
    log_event(
        "test_action",
        status="success",
        tool="search_files",
        risk_level="low",
        session_id="sess-1",
        input_summary="query='report'",
        result_summary="3 matches",
        duration_ms=42,
        conn=migrated_conn,
    )
    row = migrated_conn.execute("SELECT * FROM audit_log").fetchone()
    assert row["action"] == "test_action"
    assert row["status"] == "success"
    assert row["tool"] == "search_files"
    assert row["duration_ms"] == 42


def test_log_event_scrubs_secrets(migrated_conn, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_supersecretkey123")
    from config.settings import get_settings

    get_settings.cache_clear()
    try:
        log_event(
            "provider_error",
            status="error",
            result_summary="auth failed for key gsk_supersecretkey123",
            conn=migrated_conn,
        )
        row = migrated_conn.execute(
            "SELECT * FROM audit_log WHERE action='provider_error'"
        ).fetchone()
        assert "gsk_supersecretkey123" not in row["result_summary"]
    finally:
        get_settings.cache_clear()


def test_audit_action_success_records_duration(migrated_conn, monkeypatch):
    monkeypatch.setattr("security.audit.get_connection", lambda: _FakeCtx(migrated_conn))

    with audit_action("do_thing", tool="notes", risk_level="low") as entry:
        entry.result_summary = "ok"

    row = migrated_conn.execute("SELECT * FROM audit_log WHERE action='do_thing'").fetchone()
    assert row["status"] == "success"
    assert row["result_summary"] == "ok"
    assert row["duration_ms"] >= 0


def test_audit_action_error_records_error_code(migrated_conn, monkeypatch):
    monkeypatch.setattr("security.audit.get_connection", lambda: _FakeCtx(migrated_conn))

    with pytest.raises(ValueError), audit_action("do_thing_fail", tool="notes", risk_level="high"):
        raise ValueError("boom")

    row = migrated_conn.execute(
        "SELECT * FROM audit_log WHERE action='do_thing_fail'"
    ).fetchone()
    assert row["status"] == "error"
    assert row["error_code"] == "ValueError"


class _FakeCtx:
    """Minimal context manager standing in for storage.database.get_connection."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        return False

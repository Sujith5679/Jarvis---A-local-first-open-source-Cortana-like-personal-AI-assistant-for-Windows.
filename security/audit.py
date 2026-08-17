"""Audit logging.

Every important operation must be logged and traceable (spec.md §31, §61.8).
This writes to the local `audit_log` table only — never to a remote service —
and never stores secrets or raw secret-shaped values (input/result summaries
are passed through `security.secrets.scrub_secrets` before being persisted).

Usage:
    with audit_action("tool_execution", tool="search_files", risk_level="low",
                       session_id=session_id, input_summary="query='ClaimsX'") as entry:
        result = do_the_thing()
        entry.result_summary = f"{len(result)} matches"

which records status="success" with duration on normal exit, or
status="error" (with error_code) if an exception propagates.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from storage.database import get_connection

from security.secrets import known_secrets_from_settings, scrub_secrets

MAX_SUMMARY_LENGTH = 2000


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    scrubbed = scrub_secrets(text, known_secrets_from_settings())
    return scrubbed[:MAX_SUMMARY_LENGTH]


def log_event(
    action: str,
    *,
    status: str,
    tool: str | None = None,
    risk_level: str | None = None,
    session_id: str | None = None,
    input_summary: str | None = None,
    result_summary: str | None = None,
    error_code: str | None = None,
    duration_ms: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Write a single audit_log row. Never raises — audit failures must not break the app."""
    row = (
        datetime.now(UTC).isoformat(),
        session_id,
        action,
        tool,
        status,
        risk_level,
        _clean(input_summary),
        _clean(result_summary),
        error_code,
        duration_ms,
    )
    try:
        if conn is not None:
            conn.execute(
                """INSERT INTO audit_log
                   (timestamp, session_id, action, tool, status, risk_level,
                    input_summary, result_summary, error_code, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        else:
            with get_connection() as c:
                c.execute(
                    """INSERT INTO audit_log
                       (timestamp, session_id, action, tool, status, risk_level,
                        input_summary, result_summary, error_code, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    row,
                )
    except Exception:
        # Audit logging must degrade gracefully, never take down the caller.
        import logging

        logging.getLogger("jarvis.audit").exception("Failed to write audit log entry")


@dataclass
class _AuditEntryHandle:
    action: str
    tool: str | None
    risk_level: str | None
    session_id: str | None
    input_summary: str | None
    result_summary: str | None = None


@contextmanager
def audit_action(
    action: str,
    *,
    tool: str | None = None,
    risk_level: str | None = None,
    session_id: str | None = None,
    input_summary: str | None = None,
) -> Iterator[_AuditEntryHandle]:
    """Context manager that times an action and always writes an audit entry."""
    entry = _AuditEntryHandle(
        action=action,
        tool=tool,
        risk_level=risk_level,
        session_id=session_id,
        input_summary=input_summary,
    )
    start = time.monotonic()
    try:
        yield entry
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_event(
            action,
            status="error",
            tool=tool,
            risk_level=risk_level,
            session_id=session_id,
            input_summary=input_summary,
            result_summary=entry.result_summary,
            error_code=type(exc).__name__,
            duration_ms=duration_ms,
        )
        raise
    else:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_event(
            action,
            status="success",
            tool=tool,
            risk_level=risk_level,
            session_id=session_id,
            input_summary=input_summary,
            result_summary=entry.result_summary,
            duration_ms=duration_ms,
        )

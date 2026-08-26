"""Voice (STT/TTS) usage/cost tracking — the audio counterpart to
storage.repositories.usage's LLM token tracking. One row per call. Backs
the "Usage & Costs" dialog (ui/usage_dialog.py).

STT rows record audio duration (what it's billed by); TTS rows record
input character count (what it's billed by — output audio duration is not
the billing basis for either cloud backend here). `session_id` follows the
same convention as llm_usage/audit_log: the current conversation id.

Recording never raises — a usage-logging failure must not break a voice
turn, same rule storage.repositories.usage.record_usage and
security/audit.py's log_event follow.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from voice.pricing import estimate_stt_cost_usd, estimate_tts_cost_usd

from storage.database import get_connection

logger = logging.getLogger("jarvis.storage.voice_usage")


def _insert(
    session_id: str,
    kind: str,
    provider: str,
    model: str,
    quantity: float,
    unit: str,
    cost: float | None,
    conn: sqlite3.Connection | None,
) -> None:
    row = (
        datetime.now(UTC).isoformat(),
        session_id,
        kind,
        provider,
        model,
        quantity,
        unit,
        cost,
    )
    sql = (
        "INSERT INTO voice_usage "
        "(timestamp, session_id, kind, provider, model, quantity, unit, estimated_cost_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        if conn is not None:
            conn.execute(sql, row)
        else:
            with get_connection() as c:
                c.execute(sql, row)
    except Exception:
        logger.exception("Failed to record voice usage")


def record_stt_usage(
    session_id: str,
    provider: str,
    model: str,
    audio_seconds: float,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Logs one transcription call. Never raises."""
    cost = estimate_stt_cost_usd(provider, model, audio_seconds)
    _insert(session_id, "stt", provider, model, audio_seconds, "audio_seconds", cost, conn)


def record_tts_usage(
    session_id: str,
    provider: str,
    model: str,
    char_count: int,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Logs one synthesis call. Never raises."""
    cost = estimate_tts_cost_usd(provider, model, char_count)
    _insert(session_id, "tts", provider, model, char_count, "characters", cost, conn)


def _empty_totals() -> dict:
    return {
        "call_count": 0,
        "estimated_cost_usd": None,
        "by_provider": [],
    }


def _totals(conn: sqlite3.Connection, *, session_id: str | None) -> dict:
    where = "WHERE session_id = ?" if session_id is not None else ""
    params: tuple = (session_id,) if session_id is not None else ()

    overall = conn.execute(
        f"""SELECT COUNT(*) AS call_count, SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM voice_usage {where}""",
        params,
    ).fetchone()

    by_provider = conn.execute(
        f"""SELECT kind, provider, model,
                   COUNT(*) AS call_count,
                   SUM(quantity) AS quantity,
                   unit,
                   SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM voice_usage {where}
            GROUP BY kind, provider, model, unit
            ORDER BY kind, call_count DESC""",
        params,
    ).fetchall()

    # No rows -> SUM(estimated_cost_usd) comes back NULL (not 0), which reads
    # the same as "no priced provider" - use the explicit zeroed shape
    # instead so an empty session/history is unambiguous.
    result = _empty_totals() if overall["call_count"] == 0 else dict(overall)
    result["by_provider"] = [dict(row) for row in by_provider]
    return result


def get_session_totals(session_id: str, conn: sqlite3.Connection | None = None) -> dict:
    if conn is not None:
        return _totals(conn, session_id=session_id)
    with get_connection() as c:
        return _totals(c, session_id=session_id)


def get_overall_totals(conn: sqlite3.Connection | None = None) -> dict:
    if conn is not None:
        return _totals(conn, session_id=None)
    with get_connection() as c:
        return _totals(c, session_id=None)


def list_recent(limit: int = 50, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        rows = c.execute(
            "SELECT * FROM voice_usage ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

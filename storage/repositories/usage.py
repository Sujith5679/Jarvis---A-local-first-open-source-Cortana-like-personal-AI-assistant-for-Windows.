"""LLM usage/cost tracking — one row per call (spec.md §36-adjacent; not in
the original spec, added for cost visibility). Backs the "Usage & Costs"
dialog (ui/usage_dialog.py).

`session_id` follows audit_log's existing convention (security/audit.py):
the current conversation id, since each app launch creates a new
conversation (ui/chat_window.py). `estimated_cost_usd` is NULL whenever
llm.pricing has no known per-token price for that provider/model — most
notably Ollama Cloud, which bills a flat GPU-time subscription, not per
token. Callers must display NULL as "not applicable", never as zero.

Recording never raises — a usage-logging failure must not break a chat
turn, same rule audit_log follows (security/audit.py's log_event).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from llm.base import TokenUsage
from llm.pricing import estimate_cost_usd

from storage.database import get_connection

logger = logging.getLogger("jarvis.storage.usage")


def record_usage(
    session_id: str,
    provider: str,
    model: str,
    usage: TokenUsage,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Logs one LLM call's token usage and estimated cost. Never raises."""
    cost = estimate_cost_usd(provider, model, usage)
    row = (
        datetime.now(UTC).isoformat(),
        session_id,
        provider,
        model,
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.total_tokens,
        cost,
    )
    sql = (
        "INSERT INTO llm_usage "
        "(timestamp, session_id, provider, model, prompt_tokens, completion_tokens, "
        " total_tokens, estimated_cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        if conn is not None:
            conn.execute(sql, row)
        else:
            with get_connection() as c:
                c.execute(sql, row)
    except Exception:
        logger.exception("Failed to record LLM usage")


def _empty_totals() -> dict:
    return {
        "call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": None,
        "by_provider": [],
    }


def _totals(conn: sqlite3.Connection, *, session_id: str | None) -> dict:
    where = "WHERE session_id = ?" if session_id is not None else ""
    params: tuple = (session_id,) if session_id is not None else ()

    overall = conn.execute(
        f"""SELECT COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM llm_usage {where}""",
        params,
    ).fetchone()

    by_provider = conn.execute(
        f"""SELECT provider, model,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM llm_usage {where}
            GROUP BY provider, model
            ORDER BY total_tokens DESC""",
        params,
    ).fetchall()

    # No rows -> SUM(estimated_cost_usd) would come back NULL (not 0), which
    # reads the same as "no priced provider" - use the explicit zeroed shape
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
            "SELECT * FROM llm_usage ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

from __future__ import annotations

from llm.base import TokenUsage
from storage.repositories import usage as usage_repo


def _usage(prompt=10, completion=20) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def test_record_and_get_session_totals(real_db):
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(100, 50))
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(200, 100))
    usage_repo.record_usage("session-2", "groq", "openai/gpt-oss-120b", _usage(9999, 9999))

    totals = usage_repo.get_session_totals("session-1")
    assert totals["call_count"] == 2
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 150
    assert totals["total_tokens"] == 450
    assert totals["estimated_cost_usd"] is not None
    assert totals["estimated_cost_usd"] > 0


def test_empty_session_returns_zeroed_totals(real_db):
    totals = usage_repo.get_session_totals("no-such-session")
    assert totals["call_count"] == 0
    assert totals["total_tokens"] == 0
    assert totals["estimated_cost_usd"] is None
    assert totals["by_provider"] == []


def test_overall_totals_include_every_session(real_db):
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(10, 10))
    usage_repo.record_usage("session-2", "groq", "openai/gpt-oss-120b", _usage(20, 20))

    overall = usage_repo.get_overall_totals()
    assert overall["call_count"] == 2
    assert overall["total_tokens"] == 60


def test_unpriced_provider_cost_is_none_not_zero(real_db):
    # Ollama Cloud has no per-token price (llm/pricing.py) - a flat GPU-time
    # subscription instead - so its rows and any totals built purely from
    # them must report cost as None, never a fabricated 0.0.
    usage_repo.record_usage("session-1", "ollama_cloud", "gpt-oss:120b", _usage(500, 500))

    totals = usage_repo.get_session_totals("session-1")
    assert totals["call_count"] == 1
    assert totals["total_tokens"] == 1000
    assert totals["estimated_cost_usd"] is None

    by_provider = totals["by_provider"]
    assert len(by_provider) == 1
    assert by_provider[0]["provider"] == "ollama_cloud"
    assert by_provider[0]["estimated_cost_usd"] is None


def test_by_provider_breakdown_groups_by_provider_and_model(real_db):
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(10, 10))
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(10, 10))
    usage_repo.record_usage("session-1", "ollama_cloud", "gpt-oss:120b", _usage(10, 10))

    totals = usage_repo.get_session_totals("session-1")
    by_provider = {row["provider"]: row for row in totals["by_provider"]}
    assert by_provider["groq"]["call_count"] == 2
    assert by_provider["ollama_cloud"]["call_count"] == 1


def test_list_recent_returns_newest_first(real_db):
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(1, 1))
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(2, 2))
    usage_repo.record_usage("session-1", "groq", "openai/gpt-oss-120b", _usage(3, 3))

    recent = usage_repo.list_recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["prompt_tokens"] == 3
    assert recent[1]["prompt_tokens"] == 2


def test_record_usage_never_raises_on_bad_connection():
    # No real_db fixture here on purpose - get_connection() will fail against
    # whatever default path exists, and record_usage must swallow that
    # rather than crash the chat turn it's called from mid-agent-loop.
    import sqlite3

    class _BadConn:
        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("no such table: llm_usage")

    usage_repo.record_usage("s", "groq", "m", _usage(1, 1), conn=_BadConn())

from __future__ import annotations

from storage.repositories import voice_usage as voice_usage_repo


def test_record_stt_and_get_session_totals(real_db):
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 30.0)
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 10.0)
    voice_usage_repo.record_stt_usage("session-2", "groq", "whisper-large-v3-turbo", 9999.0)

    totals = voice_usage_repo.get_session_totals("session-1")
    assert totals["call_count"] == 2
    assert totals["estimated_cost_usd"] is not None
    assert totals["estimated_cost_usd"] > 0


def test_record_tts_usage(real_db):
    voice_usage_repo.record_tts_usage(
        "session-1", "deepgram", "aura-2-thalia-en", char_count=500
    )
    totals = voice_usage_repo.get_session_totals("session-1")
    assert totals["call_count"] == 1
    row = totals["by_provider"][0]
    assert row["kind"] == "tts"
    assert row["unit"] == "characters"
    assert row["quantity"] == 500


def test_empty_session_returns_zeroed_totals(real_db):
    totals = voice_usage_repo.get_session_totals("no-such-session")
    assert totals["call_count"] == 0
    assert totals["estimated_cost_usd"] is None
    assert totals["by_provider"] == []


def test_local_backend_cost_is_zero_not_none(real_db):
    voice_usage_repo.record_stt_usage("session-1", "local", "base", audio_seconds=10.0)
    totals = voice_usage_repo.get_session_totals("session-1")
    assert totals["estimated_cost_usd"] == 0.0
    assert totals["by_provider"][0]["estimated_cost_usd"] == 0.0


def test_overall_totals_include_every_session(real_db):
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 10.0)
    voice_usage_repo.record_stt_usage("session-2", "groq", "whisper-large-v3-turbo", 20.0)

    overall = voice_usage_repo.get_overall_totals()
    assert overall["call_count"] == 2


def test_by_provider_breakdown_separates_stt_and_tts(real_db):
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 10.0)
    voice_usage_repo.record_tts_usage("session-1", "groq", "canopylabs/orpheus-v1-english", 100)

    totals = voice_usage_repo.get_session_totals("session-1")
    kinds = {row["kind"] for row in totals["by_provider"]}
    assert kinds == {"stt", "tts"}


def test_list_recent_returns_newest_first(real_db):
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 1.0)
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 2.0)
    voice_usage_repo.record_stt_usage("session-1", "groq", "whisper-large-v3-turbo", 3.0)

    recent = voice_usage_repo.list_recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["quantity"] == 3.0
    assert recent[1]["quantity"] == 2.0


def test_record_usage_never_raises_on_bad_connection():
    import sqlite3

    class _BadConn:
        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("no such table: voice_usage")

    voice_usage_repo.record_stt_usage("s", "groq", "m", 1.0, conn=_BadConn())
    voice_usage_repo.record_tts_usage("s", "groq", "m", 1, conn=_BadConn())

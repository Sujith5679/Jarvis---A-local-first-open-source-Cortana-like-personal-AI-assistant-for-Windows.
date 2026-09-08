from __future__ import annotations

import numpy as np
import pytest
from config.settings import Settings
from voice import tts
from voice.tts_deepgram import DeepgramTTSError
from voice.tts_groq import GroqTTSError


def _settings(**overrides) -> Settings:
    overrides.setdefault("_env_file", None)
    return Settings(**overrides)



@pytest.mark.asyncio
async def test_empty_text_returns_empty_without_calling_any_backend(monkeypatch):
    monkeypatch.setattr("voice.tts.tts_groq.synthesize", lambda *a, **kw: 1 / 0)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", lambda *a, **kw: 1 / 0)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", lambda *a, **kw: 1 / 0)

    audio, sr = await tts.synthesize("   ", _settings())
    assert audio.size == 0
    assert sr > 0


@pytest.mark.asyncio
async def test_uses_first_available_provider_in_order(monkeypatch):
    async def fake_groq(text, settings):
        return np.ones(5, dtype="float32"), 24000

    def fail(*a, **kw):
        raise AssertionError("should not be reached")

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fake_groq)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", fail)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fail)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k")
    audio, sr = await tts.synthesize("hello", settings)
    assert sr == 24000
    assert audio.size == 5


@pytest.mark.asyncio
async def test_falls_back_to_deepgram_when_groq_fails(monkeypatch):
    """Covers the real failure mode hit live: Groq's Orpheus model needs
    one-time terms acceptance, so it fails until the user does that."""

    async def failing_groq(text, settings):
        raise GroqTTSError("terms not accepted")

    async def fake_deepgram(text, settings):
        return np.ones(7, dtype="float32"), 24000

    def fail_local(*a, **kw):
        raise AssertionError("local should not be reached")

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", failing_groq)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", fake_deepgram)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fail_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k")
    audio, sr = await tts.synthesize("hello", settings)
    assert audio.size == 7


@pytest.mark.asyncio
async def test_falls_back_to_local_when_all_cloud_backends_fail(monkeypatch):
    async def failing_groq(text, settings):
        raise GroqTTSError("terms not accepted")

    async def failing_deepgram(text, settings):
        raise DeepgramTTSError("also down")

    def fake_local(text, settings=None):
        return np.ones(3, dtype="float32"), 22050

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", failing_groq)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", failing_deepgram)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k")
    audio, sr = await tts.synthesize("hello", settings)
    assert sr == 22050
    assert audio.size == 3


@pytest.mark.asyncio
async def test_skips_backends_without_configured_keys(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("should be skipped: no key")

    def fake_local(text, settings=None):
        return np.ones(3, dtype="float32"), 22050

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fail)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", fail)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = _settings(GROQ_API_KEY=None, DEEPGRAM_API_KEY=None)
    audio, sr = await tts.synthesize("hello", settings)
    assert audio.size == 3


@pytest.mark.asyncio
async def test_explicit_local_only_skips_all_cloud_backends(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("cloud backend should not be called")

    def fake_local(text, settings=None):
        return np.ones(3, dtype="float32"), 22050

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fail)
    monkeypatch.setattr("voice.tts.tts_deepgram.synthesize", fail)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k", JARVIS_TTS_PROVIDERS="local")
    audio, sr = await tts.synthesize("hello", settings)
    assert audio.size == 3


# --- Usage recording: only happens when the caller passes a session_id
# (ad-hoc/test calls without one must not pollute voice_usage).


@pytest.mark.asyncio
async def test_records_usage_when_session_id_given(monkeypatch, real_db):
    from storage.repositories import voice_usage as voice_usage_repo

    async def fake_groq(text, settings):
        return np.ones(5, dtype="float32"), 24000

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fake_groq)

    settings = _settings(GROQ_API_KEY="k")
    await tts.synthesize("hello there", settings, session_id="session-1")

    totals = voice_usage_repo.get_session_totals("session-1")
    assert totals["call_count"] == 1
    assert totals["by_provider"][0]["provider"] == "groq"
    assert totals["by_provider"][0]["quantity"] == len("hello there")


@pytest.mark.asyncio
async def test_no_session_id_records_nothing(monkeypatch, real_db):
    from storage.repositories import voice_usage as voice_usage_repo

    async def fake_groq(text, settings):
        return np.ones(5, dtype="float32"), 24000

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fake_groq)

    settings = _settings(GROQ_API_KEY="k")
    await tts.synthesize("hello there", settings)

    assert voice_usage_repo.get_overall_totals()["call_count"] == 0

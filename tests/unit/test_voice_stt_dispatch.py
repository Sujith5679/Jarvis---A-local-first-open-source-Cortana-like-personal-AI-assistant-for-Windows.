from __future__ import annotations

import numpy as np
import pytest
from config.settings import Settings
from voice import stt
from voice.stt_groq import GroqSTTError


@pytest.mark.asyncio
async def test_empty_audio_returns_empty_without_calling_any_backend(monkeypatch):
    calls = []
    monkeypatch.setattr("voice.stt.stt_groq.transcribe", lambda *a, **kw: calls.append("groq"))
    monkeypatch.setattr("voice.stt.stt_local.transcribe", lambda *a, **kw: calls.append("local"))

    result = await stt.transcribe(np.zeros(0, dtype="float32"), 16000, Settings())
    assert result == ""
    assert calls == []


@pytest.mark.asyncio
async def test_uses_groq_when_configured_and_available(monkeypatch):
    async def fake_groq(audio, sample_rate, settings):
        return "from groq"

    def fake_local(audio, sample_rate):
        raise AssertionError("local should not be called when groq succeeds")

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fake_groq)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_STT_PROVIDER="groq")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from groq"


@pytest.mark.asyncio
async def test_falls_back_to_local_when_groq_fails(monkeypatch):
    async def failing_groq(audio, sample_rate, settings):
        raise GroqSTTError("rate limited")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", failing_groq)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_STT_PROVIDER="groq")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"


@pytest.mark.asyncio
async def test_explicit_local_provider_skips_groq_entirely(monkeypatch):
    def fake_groq(*a, **kw):
        raise AssertionError("groq should not be called when provider=local")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fake_groq)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_STT_PROVIDER="local")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"


@pytest.mark.asyncio
async def test_no_groq_key_uses_local_even_if_provider_is_groq(monkeypatch):
    def fake_groq(*a, **kw):
        raise AssertionError("groq should not be called without an API key")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fake_groq)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = Settings(GROQ_API_KEY=None, JARVIS_STT_PROVIDER="groq")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"

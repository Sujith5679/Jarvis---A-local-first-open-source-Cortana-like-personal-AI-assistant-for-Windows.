from __future__ import annotations

import numpy as np
import pytest
from config.settings import Settings
from voice import stt
from voice.stt_deepgram import DeepgramSTTError
from voice.stt_groq import GroqSTTError


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


@pytest.mark.asyncio
async def test_empty_audio_returns_empty_without_calling_any_backend(monkeypatch):
    monkeypatch.setattr("voice.stt.stt_groq.transcribe", lambda *a, **kw: 1 / 0)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", lambda *a, **kw: 1 / 0)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", lambda *a, **kw: 1 / 0)

    result = await stt.transcribe(np.zeros(0, dtype="float32"), 16000, _settings())
    assert result == ""


@pytest.mark.asyncio
async def test_uses_first_available_provider_in_order(monkeypatch):
    async def fake_groq(audio, sample_rate, settings):
        return "from groq"

    def fail(*a, **kw):
        raise AssertionError("should not be reached")

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fake_groq)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", fail)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fail)

    settings = _settings(
        GROQ_API_KEY="k", DEEPGRAM_API_KEY="k", JARVIS_STT_PROVIDERS="groq,deepgram,local"
    )
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from groq"


@pytest.mark.asyncio
async def test_falls_back_to_deepgram_when_groq_fails(monkeypatch):
    async def failing_groq(audio, sample_rate, settings):
        raise GroqSTTError("rate limited")

    async def fake_deepgram(audio, sample_rate, settings):
        return "from deepgram"

    def fail_local(*a, **kw):
        raise AssertionError("local should not be reached")

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", failing_groq)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", fake_deepgram)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fail_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from deepgram"


@pytest.mark.asyncio
async def test_falls_back_to_local_when_all_cloud_backends_fail(monkeypatch):
    async def failing_groq(audio, sample_rate, settings):
        raise GroqSTTError("rate limited")

    async def failing_deepgram(audio, sample_rate, settings):
        raise DeepgramSTTError("also down")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", failing_groq)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", failing_deepgram)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"


@pytest.mark.asyncio
async def test_skips_backends_without_configured_keys(monkeypatch):
    def fail_groq(*a, **kw):
        raise AssertionError("groq should be skipped: no key")

    def fail_deepgram(*a, **kw):
        raise AssertionError("deepgram should be skipped: no key")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fail_groq)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", fail_deepgram)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = _settings(GROQ_API_KEY=None, DEEPGRAM_API_KEY=None)
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"


@pytest.mark.asyncio
async def test_explicit_local_only_skips_all_cloud_backends(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("cloud backend should not be called")

    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_groq.transcribe", fail)
    monkeypatch.setattr("voice.stt.stt_deepgram.transcribe", fail)
    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = _settings(GROQ_API_KEY="k", DEEPGRAM_API_KEY="k", JARVIS_STT_PROVIDERS="local")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"


@pytest.mark.asyncio
async def test_unknown_provider_name_is_skipped_with_warning(monkeypatch):
    def fake_local(audio, sample_rate):
        return "from local"

    monkeypatch.setattr("voice.stt.stt_local.transcribe", fake_local)

    settings = _settings(JARVIS_STT_PROVIDERS="not_a_real_provider,local")
    result = await stt.transcribe(np.ones(10, dtype="float32"), 16000, settings)
    assert result == "from local"

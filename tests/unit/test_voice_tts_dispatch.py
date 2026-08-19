from __future__ import annotations

import numpy as np
import pytest
from config.settings import Settings
from voice import tts
from voice.tts_groq import GroqTTSError


@pytest.mark.asyncio
async def test_empty_text_returns_empty_without_calling_any_backend(monkeypatch):
    monkeypatch.setattr(
        "voice.tts.tts_groq.synthesize",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    monkeypatch.setattr(
        "voice.tts.tts_local.synthesize",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    audio, sr = await tts.synthesize("   ", Settings())
    assert audio.size == 0
    assert sr > 0


@pytest.mark.asyncio
async def test_uses_groq_when_configured_and_available(monkeypatch):
    async def fake_groq(text, settings):
        return np.ones(5, dtype="float32"), 24000

    def fake_local(text, settings=None):
        raise AssertionError("local should not be called when groq succeeds")

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fake_groq)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_TTS_PROVIDER="groq")
    audio, sr = await tts.synthesize("hello", settings)
    assert sr == 24000
    assert audio.size == 5


@pytest.mark.asyncio
async def test_falls_back_to_local_when_groq_fails(monkeypatch):
    """Covers the real failure mode hit live: Groq's Orpheus model needs
    one-time terms acceptance, so it fails until the user does that — this
    must transparently degrade to local rather than losing the reply."""

    async def failing_groq(text, settings):
        raise GroqTTSError("terms not accepted")

    def fake_local(text, settings=None):
        return np.ones(3, dtype="float32"), 22050

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", failing_groq)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_TTS_PROVIDER="groq")
    audio, sr = await tts.synthesize("hello", settings)
    assert sr == 22050
    assert audio.size == 3


@pytest.mark.asyncio
async def test_explicit_local_provider_skips_groq_entirely(monkeypatch):
    def fake_groq(*a, **kw):
        raise AssertionError("groq should not be called when provider=local")

    def fake_local(text, settings=None):
        return np.ones(3, dtype="float32"), 22050

    monkeypatch.setattr("voice.tts.tts_groq.synthesize", fake_groq)
    monkeypatch.setattr("voice.tts.tts_local.synthesize", fake_local)

    settings = Settings(GROQ_API_KEY="key", JARVIS_TTS_PROVIDER="local")
    audio, sr = await tts.synthesize("hello", settings)
    assert sr == 22050

from __future__ import annotations

import asyncio
import io
import wave

import httpx
import numpy as np
import pytest
from config.settings import Settings
from voice.tts_deepgram import DeepgramTTSError, _wav_bytes_to_array, synthesize


def _settings() -> Settings:
    return Settings(DEEPGRAM_API_KEY="test-key")


def _make_wav_bytes(sample_rate: int = 24000, num_samples: int = 500) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm16 = (np.sin(np.linspace(0, 10, num_samples)) * 10000).astype(np.int16)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def test_wav_bytes_to_array_reads_real_sample_rate():
    wav_bytes = _make_wav_bytes(sample_rate=24000)
    audio, sr = _wav_bytes_to_array(wav_bytes)
    assert sr == 24000
    assert audio.dtype == np.float32
    assert audio.size == 500


def test_synthesize_no_api_key_raises():
    settings = Settings(DEEPGRAM_API_KEY=None)
    with pytest.raises(DeepgramTTSError, match="No DEEPGRAM_API_KEY"):
        asyncio.run(synthesize("hello", settings))


@pytest.mark.asyncio
async def test_synthesize_success(monkeypatch):
    wav_bytes = _make_wav_bytes()

    async def fake_post(self, url, headers=None, params=None, json=None):
        return httpx.Response(200, content=wav_bytes, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    audio, sr = await synthesize("hello", _settings())
    assert sr == 24000
    assert audio.size > 0


@pytest.mark.asyncio
async def test_synthesize_connection_error(monkeypatch):
    async def fake_post(self, url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramTTSError, match="Could not connect"):
        await synthesize("hello", _settings())


@pytest.mark.asyncio
async def test_synthesize_non_200_raises(monkeypatch):
    async def fake_post(self, url, **kw):
        return httpx.Response(401, text="unauthorized", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramTTSError, match="401"):
        await synthesize("hello", _settings())

from __future__ import annotations

import asyncio

import httpx
import numpy as np
import pytest
from config.settings import Settings
from voice.stt_deepgram import DeepgramSTTError, _audio_to_wav_bytes, transcribe


def _settings() -> Settings:
    return Settings(DEEPGRAM_API_KEY="test-key")


def test_audio_to_wav_bytes_produces_valid_wav_header():
    audio = np.zeros(1000, dtype="float32")
    wav_bytes = _audio_to_wav_bytes(audio, 16000)
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"


def test_transcribe_no_api_key_raises():
    settings = Settings(DEEPGRAM_API_KEY=None)
    with pytest.raises(DeepgramSTTError, match="No DEEPGRAM_API_KEY"):
        asyncio.run(transcribe(np.ones(100, dtype="float32"), 16000, settings))


@pytest.mark.asyncio
async def test_transcribe_success(monkeypatch):
    async def fake_post(self, url, headers=None, params=None, content=None):
        body = {
            "results": {
                "channels": [{"alternatives": [{"transcript": " hello world "}]}]
            }
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await transcribe(np.ones(100, dtype="float32"), 16000, _settings())
    assert result == "hello world"


@pytest.mark.asyncio
async def test_transcribe_connection_error(monkeypatch):
    async def fake_post(self, url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramSTTError, match="Could not connect"):
        await transcribe(np.ones(100, dtype="float32"), 16000, _settings())


@pytest.mark.asyncio
async def test_transcribe_timeout(monkeypatch):
    async def fake_post(self, url, **kw):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramSTTError, match="timed out"):
        await transcribe(np.ones(100, dtype="float32"), 16000, _settings())


@pytest.mark.asyncio
async def test_transcribe_non_200_raises(monkeypatch):
    async def fake_post(self, url, **kw):
        return httpx.Response(401, text="unauthorized", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramSTTError, match="401"):
        await transcribe(np.ones(100, dtype="float32"), 16000, _settings())


@pytest.mark.asyncio
async def test_transcribe_malformed_response_raises(monkeypatch):
    async def fake_post(self, url, **kw):
        return httpx.Response(
            200, json={"unexpected": "shape"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DeepgramSTTError, match="Unexpected"):
        await transcribe(np.ones(100, dtype="float32"), 16000, _settings())

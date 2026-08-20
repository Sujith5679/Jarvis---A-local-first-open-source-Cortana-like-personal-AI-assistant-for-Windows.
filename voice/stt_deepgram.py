"""Deepgram-hosted speech-to-text — second cloud option, after Groq
(spec.md §11's provider pattern, applied to voice).

Deepgram is a separate service from Groq/Ollama — needs its own
`DEEPGRAM_API_KEY`. Sends raw WAV bytes directly (`Content-Type: audio/wav`)
rather than Deepgram's alternative `{"url": ...}` remote-fetch mode, since
JARVIS's audio is always local and in-memory.
"""

from __future__ import annotations

import io
import logging
import wave

import httpx
import numpy as np
from config.defaults import DEFAULT_LLM_TIMEOUT_SECONDS
from config.settings import Settings

logger = logging.getLogger("jarvis.voice.stt_deepgram")

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_DEEPGRAM_STT_MODEL = "nova-3"


class DeepgramSTTError(Exception):
    pass


def _audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


async def transcribe(audio: np.ndarray, sample_rate: int, settings: Settings) -> str:
    if not settings.deepgram_api_key:
        raise DeepgramSTTError("No DEEPGRAM_API_KEY configured.")

    wav_bytes = _audio_to_wav_bytes(audio.astype("float32"), sample_rate)
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": "audio/wav",
    }
    params = {"model": DEFAULT_DEEPGRAM_STT_MODEL, "smart_format": "true"}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                DEEPGRAM_LISTEN_URL, headers=headers, params=params, content=wav_bytes
            )
    except httpx.ConnectError as exc:
        raise DeepgramSTTError(f"Could not connect to Deepgram: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise DeepgramSTTError(f"Deepgram transcription timed out: {exc}") from exc

    if resp.status_code != 200:
        raise DeepgramSTTError(
            f"Deepgram transcription failed ({resp.status_code}): {resp.text[:300]}"
        )

    try:
        data = resp.json()
        return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise DeepgramSTTError(f"Unexpected Deepgram response: {exc}") from exc

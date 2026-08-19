"""Groq-hosted speech-to-text (spec.md §11's provider pattern, applied to voice).

One of two STT backends — see voice/stt.py for provider selection/fallback.
Uses the same `GROQ_API_KEY` as the LLM — no separate credential to manage.
Fast (no local model load, runs on Groq's hardware) at the cost of needing
internet access and consuming Groq API quota per request.
"""

from __future__ import annotations

import io
import logging
import wave

import httpx
import numpy as np
from config.defaults import DEFAULT_LLM_TIMEOUT_SECONDS
from config.settings import Settings

logger = logging.getLogger("jarvis.voice.stt_groq")

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
# "turbo" trades a little accuracy for speed; whisper-large-v3 is the
# alternative if accuracy matters more than latency for your use case.
DEFAULT_GROQ_STT_MODEL = "whisper-large-v3-turbo"


class GroqSTTError(Exception):
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
    if not settings.groq_api_key:
        raise GroqSTTError("No GROQ_API_KEY configured.")

    wav_bytes = _audio_to_wav_bytes(audio.astype("float32"), sample_rate)
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"model": DEFAULT_GROQ_STT_MODEL}
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                GROQ_TRANSCRIPTION_URL, headers=headers, files=files, data=data
            )
    except httpx.ConnectError as exc:
        raise GroqSTTError(f"Could not connect to Groq: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise GroqSTTError(f"Groq transcription timed out: {exc}") from exc

    if resp.status_code != 200:
        raise GroqSTTError(f"Groq transcription failed ({resp.status_code}): {resp.text[:300]}")

    try:
        return resp.json()["text"].strip()
    except (KeyError, ValueError) as exc:
        raise GroqSTTError(f"Unexpected Groq transcription response: {exc}") from exc

"""Groq-hosted text-to-speech (Orpheus model) (spec.md §11's provider
pattern, applied to voice).

One of two TTS backends — see voice/tts.py for provider selection/fallback.
Uses the same `GROQ_API_KEY` as the LLM. NOTE: canopylabs/orpheus-v1-english
requires a one-time terms acceptance in the Groq console before API calls
succeed (https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english)
— until then this backend fails and the dispatcher falls back to local Piper.

The response's actual sample rate is read from the WAV header rather than
assumed, so this stays correct even if Groq changes it.
"""

from __future__ import annotations

import io
import logging
import wave

import httpx
import numpy as np
from config.defaults import DEFAULT_LLM_TIMEOUT_SECONDS
from config.settings import Settings

logger = logging.getLogger("jarvis.voice.tts_groq")

GROQ_SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech"
DEFAULT_GROQ_TTS_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_GROQ_TTS_VOICE = "tara"


class GroqTTSError(Exception):
    pass


def _wav_bytes_to_array(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm16 = np.frombuffer(raw, dtype=np.int16)
    audio = pcm16.astype(np.float32) / 32768.0
    return audio, sample_rate


async def synthesize(text: str, settings: Settings) -> tuple[np.ndarray, int]:
    if not settings.groq_api_key:
        raise GroqTTSError("No GROQ_API_KEY configured.")

    payload = {
        "model": DEFAULT_GROQ_TTS_MODEL,
        "input": text,
        "voice": DEFAULT_GROQ_TTS_VOICE,
        "response_format": "wav",
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(GROQ_SPEECH_URL, headers=headers, json=payload)
    except httpx.ConnectError as exc:
        raise GroqTTSError(f"Could not connect to Groq: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise GroqTTSError(f"Groq speech synthesis timed out: {exc}") from exc

    if resp.status_code != 200:
        raise GroqTTSError(
            f"Groq speech synthesis failed ({resp.status_code}): {resp.text[:300]}"
        )

    try:
        return _wav_bytes_to_array(resp.content)
    except Exception as exc:
        raise GroqTTSError(f"Unexpected Groq speech response: {exc}") from exc

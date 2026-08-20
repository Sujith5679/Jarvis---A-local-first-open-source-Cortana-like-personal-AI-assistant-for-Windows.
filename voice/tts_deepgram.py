"""Deepgram-hosted text-to-speech (Aura model) — second cloud option, after
Groq (spec.md §11's provider pattern, applied to voice).

Deepgram is a separate service from Groq/Ollama — needs its own
`DEEPGRAM_API_KEY`. Requests linear16 PCM in a WAV container so the
response can be parsed the same way as Groq's WAV output (real sample rate
read from the header, never assumed).
"""

from __future__ import annotations

import io
import logging
import wave

import httpx
import numpy as np
from config.defaults import DEFAULT_LLM_TIMEOUT_SECONDS
from config.settings import Settings

logger = logging.getLogger("jarvis.voice.tts_deepgram")

DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
DEFAULT_DEEPGRAM_TTS_MODEL = "aura-2-thalia-en"


class DeepgramTTSError(Exception):
    pass


def _wav_bytes_to_array(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        sample_rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm16 = np.frombuffer(raw, dtype=np.int16)
    audio = pcm16.astype(np.float32) / 32768.0
    return audio, sample_rate


async def synthesize(text: str, settings: Settings) -> tuple[np.ndarray, int]:
    if not settings.deepgram_api_key:
        raise DeepgramTTSError("No DEEPGRAM_API_KEY configured.")

    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": "application/json",
    }
    params = {
        "model": DEFAULT_DEEPGRAM_TTS_MODEL,
        "encoding": "linear16",
        "container": "wav",
        "sample_rate": "24000",
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                DEEPGRAM_SPEAK_URL, headers=headers, params=params, json={"text": text}
            )
    except httpx.ConnectError as exc:
        raise DeepgramTTSError(f"Could not connect to Deepgram: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise DeepgramTTSError(f"Deepgram speech synthesis timed out: {exc}") from exc

    if resp.status_code != 200:
        raise DeepgramTTSError(
            f"Deepgram speech synthesis failed ({resp.status_code}): {resp.text[:300]}"
        )

    try:
        return _wav_bytes_to_array(resp.content)
    except Exception as exc:
        raise DeepgramTTSError(f"Unexpected Deepgram speech response: {exc}") from exc

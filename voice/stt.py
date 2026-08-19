"""Speech-to-text provider dispatch (spec.md §24), mirroring `llm/manager.py`'s
Groq-primary/fallback pattern for the LLM.

Two backends behind one interface:
- "groq" (voice/stt_groq.py): Groq's hosted Whisper API, same GROQ_API_KEY
  as the LLM. Fast, no local RAM/CPU cost, needs internet + API quota.
- "local" (voice/stt_local.py): faster-whisper, fully offline. Heavier and
  slower, but works with no internet and no account.

Selected via `JARVIS_STT_PROVIDER` (default "groq" once a Groq key is
configured). If the configured provider is "groq" but fails for any reason
(rate limit, network, terms not accepted, no key), this falls back to local
rather than failing the request outright — local is always available.
Explicitly choosing "local" skips Groq entirely (e.g. for offline/privacy
use), matching spec.md §33/§34.
"""

from __future__ import annotations

import logging

import numpy as np
from config.settings import Settings, get_settings

from voice import stt_groq, stt_local
from voice.stt_local import TranscriptionError

__all__ = ["TranscriptionError", "transcribe"]

logger = logging.getLogger("jarvis.voice.stt")


async def transcribe(
    audio: np.ndarray, sample_rate: int, settings: Settings | None = None
) -> str:
    if audio.size == 0:
        return ""
    settings = settings or get_settings()

    if settings.stt_provider == "groq" and settings.has_groq():
        try:
            return await stt_groq.transcribe(audio, sample_rate, settings)
        except Exception as exc:
            logger.warning("Groq STT failed, falling back to local: %s", exc)

    return stt_local.transcribe(audio, sample_rate)

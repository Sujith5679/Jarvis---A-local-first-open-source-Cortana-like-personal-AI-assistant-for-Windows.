"""Text-to-speech provider dispatch (spec.md §24), mirroring `llm/manager.py`'s
Groq-primary/fallback pattern for the LLM.

Two backends behind one interface:
- "groq" (voice/tts_groq.py): Groq's hosted Orpheus model, same
  GROQ_API_KEY as the LLM. Fast, no local RAM/CPU cost. Requires a one-time
  terms acceptance in the Groq console before it works — see README.
- "local" (voice/tts_local.py): Piper, fully offline.

Selected via `JARVIS_TTS_PROVIDER` (default "groq"). Falls back to local on
any Groq failure — including "terms not accepted" — so once you accept the
Orpheus terms, Groq TTS starts working with no further config change;
until then it transparently degrades to local. Explicitly choosing "local"
skips Groq entirely.
"""

from __future__ import annotations

import logging

import numpy as np
from config.settings import Settings, get_settings

from voice import tts_groq, tts_local
from voice.tts_local import SynthesisError

__all__ = ["SynthesisError", "synthesize"]

logger = logging.getLogger("jarvis.voice.tts")

DEFAULT_SAMPLE_RATE = 22050


async def synthesize(text: str, settings: Settings | None = None) -> tuple[np.ndarray, int]:
    text = (text or "").strip()
    settings = settings or get_settings()
    if not text:
        return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE

    if settings.tts_provider == "groq" and settings.has_groq():
        try:
            return await tts_groq.synthesize(text, settings)
        except Exception as exc:
            logger.warning("Groq TTS failed, falling back to local: %s", exc)

    return tts_local.synthesize(text, settings)

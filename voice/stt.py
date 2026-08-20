"""Speech-to-text provider dispatch (spec.md §24), mirroring `llm/manager.py`'s
provider-chain pattern for the LLM.

Three backends behind one interface, tried in the configured order:
- "groq" (voice/stt_groq.py): Groq's hosted Whisper API, same GROQ_API_KEY
  as the LLM.
- "deepgram" (voice/stt_deepgram.py): Deepgram's Listen API, separate
  DEEPGRAM_API_KEY.
- "local" (voice/stt_local.py): faster-whisper, fully offline, no key.

Order configured via `JARVIS_STT_PROVIDERS` (comma-separated, default
"groq,deepgram,local"). A backend without its API key configured is skipped
automatically. "local" is always attempted as a final safety net — even if
left out of the configured chain, or if every configured provider fails —
so voice never simply stops working as long as local is usable. Explicitly
setting `JARVIS_STT_PROVIDERS=local` skips every cloud backend, for
offline/privacy use (spec.md §33/§34).

Before any backend is tried, `voice.audio.is_silent()` gates out audio
that's too short or too quiet to plausibly contain speech. This matters
because Whisper-family models (every backend here is Whisper-based, local
or Groq-hosted alike) don't say "I heard nothing" on near-silent input —
they confidently hallucinate a stock phrase, most infamously "Thank you.",
learned from YouTube caption data full of silent clips captioned that way.

NOTE: cloud backends are called via `module.transcribe(...)` — a fresh
attribute lookup on the module object at call time, not a pre-bound
function reference — specifically so tests can monkeypatch
`voice.stt_groq.transcribe` (etc.) and have the dispatcher actually pick it
up. Binding `stt_groq.transcribe` into a dict at import time would capture
the original function forever, silently defeating that monkeypatching (and
sending real HTTP requests during "mocked" tests).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from config.settings import Settings, get_settings

from voice import stt_deepgram, stt_groq, stt_local
from voice.audio import is_silent
from voice.stt_local import TranscriptionError

__all__ = ["TranscriptionError", "transcribe"]

logger = logging.getLogger("jarvis.voice.stt")

_CLOUD_MODULES = {"groq": stt_groq, "deepgram": stt_deepgram}
_CLOUD_AVAILABILITY: dict[str, Callable[[Settings], bool]] = {
    "groq": Settings.has_groq,
    "deepgram": Settings.has_deepgram,
}


async def transcribe(
    audio: np.ndarray, sample_rate: int, settings: Settings | None = None
) -> str:
    if is_silent(audio, sample_rate):
        # Too short/quiet to plausibly contain speech - deliberately never
        # reaches any backend. Whisper-family models (local and Groq's
        # hosted whisper-large-v3-turbo alike) hallucinate confident stock
        # phrases like "Thank you." on near-silent audio instead of
        # reporting they heard nothing; see voice/audio.py's is_silent().
        return ""
    settings = settings or get_settings()

    tried_local = False
    last_exc: Exception | None = None
    for name in settings.stt_providers:
        if name == "local":
            tried_local = True
            try:
                return stt_local.transcribe(audio, sample_rate)
            except Exception as exc:
                logger.warning("local STT failed: %s", exc)
                last_exc = exc
            continue

        module = _CLOUD_MODULES.get(name)
        is_available = _CLOUD_AVAILABILITY.get(name)
        if module is None or is_available is None:
            logger.warning("Unknown STT provider %r in JARVIS_STT_PROVIDERS, skipping", name)
            continue
        if not is_available(settings):
            continue
        try:
            return await module.transcribe(audio, sample_rate, settings)
        except Exception as exc:
            logger.warning("%s STT failed, trying next: %s", name, exc)
            last_exc = exc

    if not tried_local:
        return stt_local.transcribe(audio, sample_rate)
    if last_exc is not None:
        raise last_exc
    return ""

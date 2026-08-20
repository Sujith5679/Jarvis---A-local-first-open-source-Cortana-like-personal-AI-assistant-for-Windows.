"""Text-to-speech provider dispatch (spec.md §24), mirroring `llm/manager.py`'s
provider-chain pattern for the LLM.

Three backends behind one interface, tried in the configured order:
- "groq" (voice/tts_groq.py): Groq's hosted Orpheus model, same
  GROQ_API_KEY as the LLM. Needs a one-time terms acceptance — see README.
- "deepgram" (voice/tts_deepgram.py): Deepgram's Aura model, separate
  DEEPGRAM_API_KEY.
- "local" (voice/tts_local.py): Piper, fully offline, no key.

Order configured via `JARVIS_TTS_PROVIDERS` (comma-separated, default
"groq,deepgram,local"). A backend without its API key configured is skipped
automatically. "local" is always attempted as a final safety net — even if
left out of the configured chain, or if every configured provider fails —
so voice never simply stops working as long as local is usable. Explicitly
setting `JARVIS_TTS_PROVIDERS=local` skips every cloud backend.

NOTE: cloud backends are called via `module.synthesize(...)` — a fresh
attribute lookup on the module object at call time, not a pre-bound
function reference — specifically so tests can monkeypatch
`voice.tts_groq.synthesize` (etc.) and have the dispatcher actually pick it
up. Binding `tts_groq.synthesize` into a dict at import time would capture
the original function forever, silently defeating that monkeypatching (and
sending real HTTP requests during "mocked" tests).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from config.settings import Settings, get_settings

from voice import tts_deepgram, tts_groq, tts_local
from voice.tts_local import SynthesisError

__all__ = ["SynthesisError", "synthesize"]

logger = logging.getLogger("jarvis.voice.tts")

DEFAULT_SAMPLE_RATE = 22050

_CLOUD_MODULES = {"groq": tts_groq, "deepgram": tts_deepgram}
_CLOUD_AVAILABILITY: dict[str, Callable[[Settings], bool]] = {
    "groq": Settings.has_groq,
    "deepgram": Settings.has_deepgram,
}


async def synthesize(text: str, settings: Settings | None = None) -> tuple[np.ndarray, int]:
    text = (text or "").strip()
    settings = settings or get_settings()
    if not text:
        return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE

    tried_local = False
    last_exc: Exception | None = None
    for name in settings.tts_providers:
        if name == "local":
            tried_local = True
            try:
                return tts_local.synthesize(text, settings)
            except Exception as exc:
                logger.warning("local TTS failed: %s", exc)
                last_exc = exc
            continue

        module = _CLOUD_MODULES.get(name)
        is_available = _CLOUD_AVAILABILITY.get(name)
        if module is None or is_available is None:
            logger.warning("Unknown TTS provider %r in JARVIS_TTS_PROVIDERS, skipping", name)
            continue
        if not is_available(settings):
            continue
        try:
            return await module.synthesize(text, settings)
        except Exception as exc:
            logger.warning("%s TTS failed, trying next: %s", name, exc)
            last_exc = exc

    if not tried_local:
        return tts_local.synthesize(text, settings)
    if last_exc is not None:
        raise last_exc
    return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE

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

Every successful call is logged via storage.repositories.voice_usage
(input character count + estimated cost — TTS is billed by input text
length, not output audio duration, for both cloud backends here) —
skipped entirely if the caller passes no `session_id`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np
from config.defaults import DEFAULT_PIPER_VOICE_NAME
from config.settings import Settings, get_settings
from storage.repositories import voice_usage as voice_usage_repo

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
_MODEL_NAMES = {
    "groq": tts_groq.DEFAULT_GROQ_TTS_MODEL,
    "deepgram": tts_deepgram.DEFAULT_DEEPGRAM_TTS_MODEL,
    "local": DEFAULT_PIPER_VOICE_NAME,
}


def _record(session_id: str | None, provider: str, char_count: int) -> None:
    if session_id is None:
        return
    voice_usage_repo.record_tts_usage(session_id, provider, _MODEL_NAMES[provider], char_count)


async def synthesize(
    text: str, settings: Settings | None = None, session_id: str | None = None
) -> tuple[np.ndarray, int]:
    text = (text or "").strip()
    settings = settings or get_settings()
    if not text:
        return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE
    char_count = len(text)

    tried_local = False
    last_exc: Exception | None = None
    for name in settings.tts_providers:
        if name == "local":
            tried_local = True
            try:
                result = tts_local.synthesize(text, settings)
                _record(session_id, "local", char_count)
                return result
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
            result = await module.synthesize(text, settings)
            _record(session_id, name, char_count)
            return result
        except Exception as exc:
            logger.warning("%s TTS failed, trying next: %s", name, exc)
            last_exc = exc

    if not tried_local:
        result = tts_local.synthesize(text, settings)
        _record(session_id, "local", char_count)
        return result
    if last_exc is not None:
        raise last_exc
    return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE

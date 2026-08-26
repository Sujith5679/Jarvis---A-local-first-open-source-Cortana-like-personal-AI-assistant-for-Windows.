"""Per-provider/model USD pricing for voice (STT/TTS) usage — the audio
counterpart to llm/pricing.py's token pricing.

STT is billed by audio duration; TTS is billed by input *character* count,
not output audio duration, for both cloud backends below. Live-verified
(Aug 2026):
- Groq whisper-large-v3-turbo (STT): $0.04/hour of audio
  (console.groq.com/docs/model/whisper-large-v3-turbo)
- Groq canopylabs/orpheus-v1-english (TTS): $22/1M characters
  (console.groq.com/docs/model/canopylabs/orpheus-v1-english)
- Deepgram nova-3 (STT, pre-recorded/batch — what voice/stt_deepgram.py
  uses, POSTing a full WAV rather than streaming; batch is priced lower
  than Deepgram's streaming tier): $0.0043/minute (deepgram.com/pricing)
- Deepgram aura-2-thalia-en (TTS): $0.030/1000 characters
  (deepgram.com/pricing)

Local backends (faster-whisper, Piper) cost a real $0.00 — genuinely free,
which is a *known* price, unlike an unpriced cloud provider (llm/pricing.py's
Ollama Cloud case) — so "local" returns 0.0 here, never None.

Re-verify periodically — provider pricing changes without notice and this
file will silently go stale otherwise.
"""

from __future__ import annotations

# (provider, model) -> price per second of audio, USD.
_STT_PRICE_PER_SECOND: dict[tuple[str, str], float] = {
    ("groq", "whisper-large-v3-turbo"): 0.04 / 3600,
    ("deepgram", "nova-3"): 0.0043 / 60,
}

# (provider, model) -> price per character of input text, USD.
_TTS_PRICE_PER_CHARACTER: dict[tuple[str, str], float] = {
    ("groq", "canopylabs/orpheus-v1-english"): 22.0 / 1_000_000,
    ("deepgram", "aura-2-thalia-en"): 0.030 / 1000,
}


def estimate_stt_cost_usd(provider: str, model: str, audio_seconds: float) -> float | None:
    """Returns the estimated USD cost of one transcription call, 0.0 for the
    local backend (genuinely free), or None if `provider`/`model` has no
    known price — never a fabricated figure."""
    if provider == "local":
        return 0.0
    price = _STT_PRICE_PER_SECOND.get((provider, model))
    if price is None:
        return None
    return audio_seconds * price


def estimate_tts_cost_usd(provider: str, model: str, char_count: int) -> float | None:
    """Returns the estimated USD cost of one synthesis call, 0.0 for the
    local backend (genuinely free), or None if `provider`/`model` has no
    known price — never a fabricated figure."""
    if provider == "local":
        return 0.0
    price = _TTS_PRICE_PER_CHARACTER.get((provider, model))
    if price is None:
        return None
    return char_count * price

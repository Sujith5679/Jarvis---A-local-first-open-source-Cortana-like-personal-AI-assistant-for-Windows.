from __future__ import annotations

from voice.pricing import estimate_stt_cost_usd, estimate_tts_cost_usd


def test_groq_stt_cost_per_hour():
    # Live-verified (console.groq.com/docs/model/whisper-large-v3-turbo,
    # Aug 2026): $0.04/hour.
    cost = estimate_stt_cost_usd("groq", "whisper-large-v3-turbo", audio_seconds=3600)
    assert cost == 0.04


def test_deepgram_stt_cost_per_minute():
    # Live-verified (deepgram.com/pricing, Aug 2026): pre-recorded/batch
    # nova-3 monolingual, $0.0043/min.
    cost = estimate_stt_cost_usd("deepgram", "nova-3", audio_seconds=60)
    assert cost == 0.0043


def test_local_stt_is_free_not_unknown():
    # Genuinely free (no API call at all) - a known $0.00, not "no pricing
    # data" - so this must be 0.0, never None.
    assert estimate_stt_cost_usd("local", "base", audio_seconds=999) == 0.0


def test_unknown_stt_provider_returns_none():
    assert estimate_stt_cost_usd("some_future_provider", "x", audio_seconds=10) is None


def test_groq_tts_cost_per_character():
    # Live-verified (console.groq.com/docs/model/canopylabs/orpheus-v1-english,
    # Aug 2026): $22/1M characters.
    cost = estimate_tts_cost_usd("groq", "canopylabs/orpheus-v1-english", char_count=1_000_000)
    assert cost == 22.0


def test_deepgram_tts_cost_per_character():
    # Live-verified (deepgram.com/pricing, Aug 2026): aura-2, $0.030/1000 chars.
    cost = estimate_tts_cost_usd("deepgram", "aura-2-thalia-en", char_count=1000)
    assert cost == 0.030


def test_local_tts_is_free_not_unknown():
    assert estimate_tts_cost_usd("local", "en_US-lessac-medium", char_count=999) == 0.0


def test_unknown_tts_provider_returns_none():
    assert estimate_tts_cost_usd("some_future_provider", "x", char_count=10) is None

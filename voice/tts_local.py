"""Local text-to-speech via Piper (spec.md §24).

One of two TTS backends — see voice/tts.py for provider selection/fallback.
Fully offline — requires a downloaded Piper voice model (see README:
`python -m piper.download_voices <name> --download-dir data/voices`). If no
voice model is found, `synthesize()` raises `SynthesisError`.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
from config.defaults import DEFAULT_PIPER_VOICE_NAME
from config.settings import Settings, get_settings

logger = logging.getLogger("jarvis.voice.tts_local")

DEFAULT_SAMPLE_RATE = 22050  # Piper's typical native rate; overridden by the loaded voice


class SynthesisError(Exception):
    pass


def resolve_voice_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    if settings.piper_voice_path:
        return Path(settings.piper_voice_path)
    return settings.voices_dir / f"{DEFAULT_PIPER_VOICE_NAME}.onnx"


@lru_cache(maxsize=1)
def _get_voice(voice_path_str: str):
    # Imported lazily: piper pulls in onnxruntime, slow to import and
    # unnecessary for anything that doesn't touch voice.
    from piper import PiperVoice

    return PiperVoice.load(voice_path_str)


def synthesize(text: str, settings: Settings | None = None) -> tuple[np.ndarray, int]:
    """Returns (mono float32 audio, sample_rate). Returns empty audio for
    empty input; raises SynthesisError if the voice model is missing or the
    engine fails."""
    text = (text or "").strip()
    if not text:
        return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE

    voice_path = resolve_voice_path(settings)
    if not voice_path.exists():
        raise SynthesisError(
            f"No Piper voice model found at {voice_path}. Download one with "
            f"`python -m piper.download_voices {DEFAULT_PIPER_VOICE_NAME} "
            f"--download-dir {voice_path.parent}`."
        )

    try:
        voice = _get_voice(str(voice_path))
        chunks = list(voice.synthesize(text))
        if not chunks:
            return np.zeros(0, dtype="float32"), DEFAULT_SAMPLE_RATE
        audio = np.concatenate([c.audio_float_array for c in chunks])
        return audio, chunks[0].sample_rate
    except Exception as exc:
        logger.exception("Speech synthesis failed")
        raise SynthesisError(str(exc)) from exc

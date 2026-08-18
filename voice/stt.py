"""Local speech-to-text via faster-whisper (spec.md §24).

Fully offline once the model weights are cached locally (downloaded from
Hugging Face on first use — same pattern as rag/embeddings.py's local
embedding model). STT failure must fall back to text mode (spec.md §32):
callers catch `TranscriptionError` and let the user type instead of being
blocked from using JARVIS at all.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from config.defaults import DEFAULT_WHISPER_COMPUTE_TYPE, DEFAULT_WHISPER_MODEL_SIZE

logger = logging.getLogger("jarvis.voice.stt")

WHISPER_SAMPLE_RATE = 16000  # Whisper models expect 16kHz mono audio


class TranscriptionError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_model():
    # Imported lazily: faster-whisper pulls in ctranslate2, slow to import
    # and unnecessary for anything that doesn't touch voice.
    from faster_whisper import WhisperModel

    return WhisperModel(
        DEFAULT_WHISPER_MODEL_SIZE, device="cpu", compute_type=DEFAULT_WHISPER_COMPUTE_TYPE
    )


def resample_to_16k(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Nearest-neighbor resample — recording already happens at 16kHz
    (config.defaults.DEFAULT_AUDIO_SAMPLE_RATE) so this is normally a no-op;
    kept for robustness against any other audio source."""
    if sample_rate == WHISPER_SAMPLE_RATE or audio.size == 0:
        return audio
    ratio = WHISPER_SAMPLE_RATE / sample_rate
    new_len = max(int(len(audio) * ratio), 1)
    idx = np.clip((np.arange(new_len) / ratio).astype(np.int64), 0, len(audio) - 1)
    return audio[idx]


def transcribe(audio: np.ndarray, sample_rate: int) -> str:
    """Transcribes mono float32 audio to text. Returns "" for empty/silent
    input; raises TranscriptionError on an actual engine failure."""
    if audio.size == 0:
        return ""
    try:
        model = _get_model()
        audio16k = resample_to_16k(audio.astype("float32"), sample_rate)
        segments, _info = model.transcribe(audio16k, language="en", beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as exc:
        logger.exception("Transcription failed")
        raise TranscriptionError(str(exc)) from exc

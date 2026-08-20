"""Microphone capture and audio playback (spec.md §24).

Push-to-talk capture: `AudioRecorder.start()` begins buffering microphone
input on PortAudio's own callback thread (via sounddevice) and returns
immediately; `.stop()` ends it and returns the recorded samples. Neither
call blocks — safe to invoke directly from the Qt UI thread on a
push-to-talk button's press/release events. `play_audio()` *is* blocking
(it waits for playback to finish) — callers run it on a background thread,
never the UI thread, same pattern as the agent turn worker.
"""

from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd
from config.defaults import (
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_MIN_SPEECH_DURATION_SECONDS,
    DEFAULT_MIN_SPEECH_RMS,
)

logger = logging.getLogger("jarvis.voice.audio")


class MicrophoneUnavailableError(Exception):
    pass


class AudioRecorder:
    def __init__(self, sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if status:
            logger.warning("Audio input status: %s", status)
        self._frames.append(indata.copy())

    def start(self) -> None:
        self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            raise MicrophoneUnavailableError(f"Could not access microphone: {exc}") from exc

    def stop(self) -> np.ndarray:
        """Stops recording and returns the captured mono audio (may be empty
        if start() failed or nothing was captured)."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        if not self._frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(self._frames).flatten()


def is_silent(
    audio: np.ndarray,
    sample_rate: int,
    *,
    rms_threshold: float = DEFAULT_MIN_SPEECH_RMS,
    min_duration_seconds: float = DEFAULT_MIN_SPEECH_DURATION_SECONDS,
) -> bool:
    """True if `audio` is too short or too quiet to plausibly contain real
    speech. Whisper-family models hallucinate confident stock phrases (most
    infamously "Thank you.") when fed near-silent audio rather than
    reporting they heard nothing — so callers should check this *before*
    handing audio to any STT backend, not rely on the model to know."""
    if audio.size == 0:
        return True
    if sample_rate <= 0 or audio.size / sample_rate < min_duration_seconds:
        return True
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return rms < rms_threshold


def play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Blocking playback. Call from a background thread, never the UI thread."""
    if audio.size == 0:
        return
    sd.play(audio, sample_rate)
    sd.wait()

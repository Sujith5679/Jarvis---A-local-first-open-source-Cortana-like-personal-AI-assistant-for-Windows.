from __future__ import annotations

import numpy as np
import pytest
from voice.audio import AudioRecorder, MicrophoneUnavailableError, is_silent, play_audio


class _FakeStream:
    instances: list[_FakeStream] = []

    def __init__(self, samplerate, channels, dtype, callback):
        self.samplerate = samplerate
        self.callback = callback
        self.started = False
        self.closed = False
        _FakeStream.instances.append(self)

    def start(self):
        self.started = True
        # Simulate a couple of audio blocks arriving.
        self.callback(np.ones((100, 1), dtype="float32") * 0.1, 100, None, None)
        self.callback(np.ones((50, 1), dtype="float32") * 0.2, 50, None, None)

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


def test_start_stop_returns_concatenated_audio(monkeypatch):
    monkeypatch.setattr("voice.audio.sd.InputStream", _FakeStream)
    recorder = AudioRecorder(sample_rate=16000)
    recorder.start()
    audio = recorder.stop()
    assert audio.shape == (150,)
    assert audio.dtype == np.float32


def test_stop_without_start_returns_empty():
    recorder = AudioRecorder()
    assert recorder.stop().size == 0


def test_start_wraps_stream_errors(monkeypatch):
    def _raise(*a, **kw):
        raise RuntimeError("no device")

    monkeypatch.setattr("voice.audio.sd.InputStream", _raise)
    recorder = AudioRecorder()
    with pytest.raises(MicrophoneUnavailableError):
        recorder.start()


def test_play_audio_skips_empty(monkeypatch):
    calls = []
    monkeypatch.setattr("voice.audio.sd.play", lambda *a, **kw: calls.append("play"))
    monkeypatch.setattr("voice.audio.sd.wait", lambda: calls.append("wait"))

    play_audio(np.zeros(0, dtype="float32"), 16000)
    assert calls == []


def test_play_audio_plays_and_waits(monkeypatch):
    calls = []
    monkeypatch.setattr("voice.audio.sd.play", lambda *a, **kw: calls.append("play"))
    monkeypatch.setattr("voice.audio.sd.wait", lambda: calls.append("wait"))

    play_audio(np.ones(10, dtype="float32"), 16000)
    assert calls == ["play", "wait"]


# --- is_silent(): gates near-silent/too-short audio out before it ever
# reaches a Whisper-family backend, which would otherwise hallucinate a
# confident stock phrase (e.g. "Thank you.") instead of reporting silence.


def test_empty_audio_is_silent():
    assert is_silent(np.zeros(0, dtype="float32"), 16000) is True


def test_zero_sample_rate_is_silent():
    assert is_silent(np.ones(8000, dtype="float32"), 0) is True


def test_quiet_full_length_audio_is_silent():
    quiet = np.full(8000, 0.001, dtype="float32")  # 0.5s @ 16kHz, near-zero amplitude
    assert is_silent(quiet, 16000) is True


def test_loud_but_too_short_audio_is_silent():
    brief = np.full(50, 0.5, dtype="float32")  # loud, but only a few ms
    assert is_silent(brief, 16000) is True


def test_loud_full_length_audio_is_not_silent():
    loud = np.full(8000, 0.5, dtype="float32")  # 0.5s @ 16kHz, well above the RMS floor
    assert is_silent(loud, 16000) is False


def test_custom_thresholds_are_respected():
    quiet = np.full(8000, 0.001, dtype="float32")
    assert is_silent(quiet, 16000, rms_threshold=0.0001) is False

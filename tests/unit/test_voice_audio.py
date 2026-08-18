from __future__ import annotations

import numpy as np
import pytest
from voice.audio import AudioRecorder, MicrophoneUnavailableError, play_audio


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

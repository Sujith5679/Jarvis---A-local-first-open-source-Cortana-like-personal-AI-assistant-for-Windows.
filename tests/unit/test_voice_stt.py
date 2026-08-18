from __future__ import annotations

import numpy as np
import pytest
from voice.stt import TranscriptionError, resample_to_16k, transcribe


def test_resample_noop_when_already_16k():
    audio = np.arange(100, dtype="float32")
    assert np.array_equal(resample_to_16k(audio, 16000), audio)


def test_resample_changes_length_proportionally():
    audio = np.arange(1000, dtype="float32")
    resampled = resample_to_16k(audio, 32000)  # half rate -> half length
    assert abs(len(resampled) - 500) <= 1


def test_resample_empty_audio():
    assert resample_to_16k(np.zeros(0, dtype="float32"), 8000).size == 0


def test_transcribe_empty_audio_returns_empty_string_without_loading_model():
    # No monkeypatching of _get_model — if this tried to load the real model
    # it would take ~30s; empty input must short-circuit before that.
    assert transcribe(np.zeros(0, dtype="float32"), 16000) == ""


def test_transcribe_wraps_engine_failure(monkeypatch):
    class _FailingModel:
        def transcribe(self, *a, **kw):
            raise RuntimeError("engine exploded")

    monkeypatch.setattr("voice.stt._get_model", lambda: _FailingModel())
    with pytest.raises(TranscriptionError):
        transcribe(np.ones(100, dtype="float32"), 16000)


def test_transcribe_joins_segments(monkeypatch):
    class _Segment:
        def __init__(self, text):
            self.text = text

    class _FakeModel:
        def transcribe(self, audio, language, beam_size):
            return [_Segment(" hello "), _Segment("world ")], object()

    monkeypatch.setattr("voice.stt._get_model", lambda: _FakeModel())
    result = transcribe(np.ones(100, dtype="float32"), 16000)
    assert result == "hello world"


@pytest.mark.slow
def test_transcribe_real_model_roundtrip():
    """One real end-to-end test with the actual faster-whisper model (slow:
    downloads/loads the model on first run). Uses Piper to generate a short,
    known utterance rather than requiring a real microphone."""
    from piper import PiperVoice
    from voice.tts import resolve_voice_path

    voice_path = resolve_voice_path()
    if not voice_path.exists():
        pytest.skip(f"No Piper voice model at {voice_path}; run the download step first.")

    voice = PiperVoice.load(str(voice_path))
    chunks = list(voice.synthesize("open the settings"))
    audio = np.concatenate([c.audio_float_array for c in chunks])
    sample_rate = chunks[0].sample_rate

    text = transcribe(audio, sample_rate)
    assert "settings" in text.lower()

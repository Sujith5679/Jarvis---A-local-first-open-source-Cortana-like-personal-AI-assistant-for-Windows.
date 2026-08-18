from __future__ import annotations

import numpy as np
import pytest
from voice.tts import SynthesisError, resolve_voice_path, synthesize


def test_empty_text_returns_empty_audio_without_loading_engine():
    audio, sr = synthesize("   ")
    assert audio.size == 0
    assert sr > 0


def test_missing_voice_model_raises_synthesis_error(tmp_path, monkeypatch):
    from config.settings import get_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_PIPER_VOICE_PATH", str(tmp_path / "does_not_exist.onnx"))
    get_settings.cache_clear()
    try:
        with pytest.raises(SynthesisError, match="No Piper voice model"):
            synthesize("hello")
    finally:
        get_settings.cache_clear()


def test_resolve_voice_path_uses_override(tmp_path, monkeypatch):
    from config.settings import get_settings

    override = tmp_path / "custom_voice.onnx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_PIPER_VOICE_PATH", str(override))
    get_settings.cache_clear()
    try:
        assert resolve_voice_path() == override
    finally:
        get_settings.cache_clear()


def test_synthesize_engine_failure_wrapped(monkeypatch, tmp_path):
    voice_path = tmp_path / "voice.onnx"
    voice_path.write_bytes(b"fake")  # just needs to exist

    class _FailingVoice:
        def synthesize(self, text):
            raise RuntimeError("onnx exploded")

    monkeypatch.setattr("voice.tts.resolve_voice_path", lambda settings=None: voice_path)
    monkeypatch.setattr("voice.tts._get_voice", lambda path: _FailingVoice())

    with pytest.raises(SynthesisError):
        synthesize("hello")


def test_synthesize_real_voice_produces_valid_audio():
    """Real end-to-end test against the downloaded Piper voice model."""
    voice_path = resolve_voice_path()
    if not voice_path.exists():
        pytest.skip(f"No Piper voice model at {voice_path}; run the download step first.")

    audio, sample_rate = synthesize("Hello from JARVIS.")
    assert audio.dtype == np.float32
    assert audio.size > 0
    assert sample_rate > 0
    assert np.abs(audio).max() <= 1.0

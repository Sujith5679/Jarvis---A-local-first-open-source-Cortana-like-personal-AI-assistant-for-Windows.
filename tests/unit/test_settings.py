from __future__ import annotations

from config.settings import ConfigurationMode, get_settings


def test_data_dir_created(isolated_settings):
    assert isolated_settings.data_dir.exists()
    assert isolated_settings.db_path.parent == isolated_settings.data_dir


def test_defaults_when_env_missing(isolated_settings):
    assert isolated_settings.searxng_url == "http://localhost:8080"
    assert isolated_settings.jarvis_timezone == "Asia/Kolkata"
    assert isolated_settings.configuration_mode == ConfigurationMode.AUTO


def test_has_groq_false_when_unset(isolated_settings):
    assert isolated_settings.has_groq() is False
    assert isolated_settings.has_ollama_cloud() is False


def test_has_groq_true_when_key_present(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key")
    get_settings.cache_clear()
    settings = get_settings()
    try:
        assert settings.has_groq() is True
    finally:
        get_settings.cache_clear()


def test_logs_and_indexes_dirs_created(isolated_settings):
    assert isolated_settings.logs_dir.exists()
    assert isolated_settings.indexes_dir.exists()
    assert isolated_settings.cache_dir.exists()

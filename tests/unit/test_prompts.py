from __future__ import annotations

from agent.prompts import build_system_prompt


def test_prompt_states_untrusted_content_rule(isolated_settings):
    prompt = build_system_prompt(isolated_settings)
    assert "untrusted" in prompt.lower()
    assert "never claim an action succeeded" in prompt.lower()


def test_prompt_includes_timezone(isolated_settings):
    prompt = build_system_prompt(isolated_settings)
    assert isolated_settings.jarvis_timezone in prompt


def test_prompt_includes_user_name_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_USER_NAME", "Alex")
    from config.settings import get_settings

    get_settings.cache_clear()
    try:
        prompt = build_system_prompt(get_settings())
        assert "Alex" in prompt
    finally:
        get_settings.cache_clear()

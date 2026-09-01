from __future__ import annotations

from agent.prompts import MEMORY_SECTION_HEADER, build_system_prompt


def test_prompt_states_untrusted_content_rule(isolated_settings):
    prompt = build_system_prompt(isolated_settings)
    assert "untrusted" in prompt.lower()
    assert "never claim an action succeeded" in prompt.lower()


def test_prompt_includes_timezone(isolated_settings):
    prompt = build_system_prompt(isolated_settings)
    assert isolated_settings.jarvis_timezone in prompt


def test_prompt_includes_user_name_when_set(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARVIS_USER_NAME", "Alex")
    from config.settings import get_settings

    get_settings.cache_clear()
    try:
        prompt = build_system_prompt(get_settings())
        assert "Alex" in prompt
    finally:
        get_settings.cache_clear()


def test_prompt_without_memories_has_no_memory_section(isolated_settings):
    prompt = build_system_prompt(isolated_settings)
    assert MEMORY_SECTION_HEADER not in prompt


def test_prompt_with_memories_includes_them(isolated_settings):
    memories = [
        {"content": "Prefers metric units.", "memory_type": "preference"},
        {"content": "Works on a project called Aurora.", "memory_type": "knowledge"},
    ]
    prompt = build_system_prompt(isolated_settings, memories)
    assert MEMORY_SECTION_HEADER in prompt
    assert "Prefers metric units." in prompt
    assert "Works on a project called Aurora." in prompt


def test_prompt_with_empty_memories_list_has_no_memory_section(isolated_settings):
    prompt = build_system_prompt(isolated_settings, [])
    assert MEMORY_SECTION_HEADER not in prompt


def test_prompt_states_remember_only_on_explicit_request():
    from agent.prompts import BASE_SYSTEM_PROMPT

    assert "remember_fact" in BASE_SYSTEM_PROMPT
    assert "own initiative" in BASE_SYSTEM_PROMPT.lower()

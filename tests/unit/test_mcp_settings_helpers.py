from __future__ import annotations

from ui.mcp_settings import _parse_env_lines


def test_parses_valid_lines():
    env, warnings = _parse_env_lines("A=1\nB=hello world\n")
    assert env == {"A": "1", "B": "hello world"}
    assert warnings == []


def test_ignores_blank_lines():
    env, warnings = _parse_env_lines("A=1\n\n\nB=2\n")
    assert env == {"A": "1", "B": "2"}
    assert warnings == []


def test_value_may_contain_equals_sign():
    env, warnings = _parse_env_lines("URL=http://x?a=1&b=2")
    assert env == {"URL": "http://x?a=1&b=2"}
    assert warnings == []


def test_line_without_equals_is_a_warning_not_an_error():
    env, warnings = _parse_env_lines("NOT_VALID\nA=1")
    assert env == {"A": "1"}
    assert len(warnings) == 1
    assert "NOT_VALID" in warnings[0]


def test_empty_key_is_a_warning():
    env, warnings = _parse_env_lines("=novalue")
    assert env == {}
    assert len(warnings) == 1


def test_empty_input_returns_empty_env_no_warnings():
    env, warnings = _parse_env_lines("")
    assert env == {}
    assert warnings == []


def test_whitespace_around_key_and_value_is_stripped():
    env, warnings = _parse_env_lines("  KEY  =  value  ")
    assert env == {"KEY": "value"}
    assert warnings == []

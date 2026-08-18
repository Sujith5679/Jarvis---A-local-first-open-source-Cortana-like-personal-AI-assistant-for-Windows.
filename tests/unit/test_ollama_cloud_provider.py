from __future__ import annotations

import json

import httpx
import pytest
from llm.base import ProviderAuthError, ProviderRateLimitError, ProviderResponseError
from llm.ollama_cloud_provider import OllamaCloudProvider, _translate_messages


def _provider() -> OllamaCloudProvider:
    return OllamaCloudProvider(api_key="test-key", model="test-model")


def test_parse_successful_response():
    resp = httpx.Response(
        200,
        json={"model": "test-model", "message": {"content": "hi"}, "done": True},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    result = _provider()._parse_response(resp)
    assert result.content == "hi"
    assert result.provider == "ollama_cloud"
    assert result.finish_reason == "stop"


def test_parse_401_raises_auth_error():
    resp = httpx.Response(
        401, json={"error": "unauthorized"},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    with pytest.raises(ProviderAuthError):
        _provider()._parse_response(resp)


def test_parse_429_raises_rate_limit_error():
    resp = httpx.Response(
        429, json={"error": "rate limited"},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    with pytest.raises(ProviderRateLimitError):
        _provider()._parse_response(resp)


def test_parse_malformed_body_raises_response_error():
    resp = httpx.Response(
        200, json={"unexpected": "shape"},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    with pytest.raises(ProviderResponseError):
        _provider()._parse_response(resp)


# --- _translate_messages: real bug found live-testing Groq -> Ollama Cloud
# mid-turn fallback. Ollama Cloud's /api/chat rejects (HTTP 400) a
# tool_calls[].function.arguments that's a JSON-encoded string (Groq/OpenAI's
# required shape) rather than a JSON object (Ollama's required shape). See
# llm/ollama_cloud_provider.py's module docstring for the full story.


def test_translate_converts_string_arguments_to_object():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search_files", "arguments": json.dumps({"query": "x"})},
                }
            ],
        }
    ]
    translated = _translate_messages(messages)
    assert translated[0]["tool_calls"][0]["function"]["arguments"] == {"query": "x"}


def test_translate_leaves_object_arguments_unchanged():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "search_files", "arguments": {"query": "x"}}}
            ],
        }
    ]
    translated = _translate_messages(messages)
    assert translated[0]["tool_calls"][0]["function"]["arguments"] == {"query": "x"}


def test_translate_handles_empty_string_arguments():
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "x", "arguments": ""}}]}
    ]
    translated = _translate_messages(messages)
    assert translated[0]["tool_calls"][0]["function"]["arguments"] == {}


def test_translate_malformed_json_string_falls_back_to_empty_object():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "x", "arguments": "{not valid json"}}],
        }
    ]
    translated = _translate_messages(messages)
    assert translated[0]["tool_calls"][0]["function"]["arguments"] == {}


def test_translate_leaves_messages_without_tool_calls_unchanged():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    translated = _translate_messages(messages)
    assert translated == messages


def test_translate_does_not_mutate_original_messages():
    original = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "x", "arguments": json.dumps({"a": 1})}}],
        }
    ]
    _translate_messages(original)
    assert original[0]["tool_calls"][0]["function"]["arguments"] == json.dumps({"a": 1})

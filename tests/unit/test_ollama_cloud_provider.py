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


# --- Token usage extraction: live-verified shape (Aug 2026) has no "usage"
# object like Groq/OpenAI - top-level prompt_eval_count/eval_count instead,
# and no total_tokens field (summed in _extract_usage).


def test_parse_response_extracts_usage():
    resp = httpx.Response(
        200,
        json={
            "model": "test-model",
            "message": {"content": "hi"},
            "done": True,
            "prompt_eval_count": 73,
            "eval_count": 79,
        },
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    result = _provider()._parse_response(resp)
    assert result.usage is not None
    assert result.usage.prompt_tokens == 73
    assert result.usage.completion_tokens == 79
    assert result.usage.total_tokens == 152


def test_parse_response_without_eval_counts_leaves_usage_none():
    resp = httpx.Response(
        200,
        json={"model": "test-model", "message": {"content": "hi"}, "done": True},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    result = _provider()._parse_response(resp)
    assert result.usage is None


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


# --- Rate-limit-aware retry (same pattern as llm/groq_provider.py): waits
# the provider's reported reset time rather than a blind fixed backoff.


def test_parse_429_attaches_retry_after_from_standard_header():
    resp = httpx.Response(
        429,
        headers={"retry-after": "3"},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )
    with pytest.raises(ProviderRateLimitError) as excinfo:
        _provider()._parse_response(resp)
    assert excinfo.value.retry_after == 3.0


def test_parse_429_no_header_leaves_retry_after_none():
    resp = httpx.Response(
        429, request=httpx.Request("POST", "https://ollama.com/api/chat")
    )
    with pytest.raises(ProviderRateLimitError) as excinfo:
        _provider()._parse_response(resp)
    assert excinfo.value.retry_after is None


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses  # shared queue across retry attempts, not copied

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        return self._responses.pop(0)


def _rate_limited_response(retry_after: str) -> httpx.Response:
    return httpx.Response(
        429,
        headers={"retry-after": retry_after},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": "test-model", "message": {"content": "ok"}, "done": True},
        request=httpx.Request("POST", "https://ollama.com/api/chat"),
    )


@pytest.mark.asyncio
async def test_generate_waits_reported_time_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("llm.ollama_cloud_provider.asyncio.sleep", fake_sleep)

    responses = [_rate_limited_response("2"), _ok_response()]
    monkeypatch.setattr(
        "llm.ollama_cloud_provider.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(responses)
    )

    result = await _provider().generate([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_generate_gives_up_immediately_when_reset_exceeds_cap(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("llm.ollama_cloud_provider.asyncio.sleep", fake_sleep)

    responses = [_rate_limited_response("600")]  # 10 minutes — far past the cap
    monkeypatch.setattr(
        "llm.ollama_cloud_provider.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(responses)
    )

    with pytest.raises(ProviderRateLimitError):
        await _provider().generate([{"role": "user", "content": "hi"}])
    assert sleeps == []

from __future__ import annotations

import httpx
import pytest

from llm.base import ProviderAuthError, ProviderRateLimitError, ProviderResponseError
from llm.groq_provider import GroqProvider


def _provider() -> GroqProvider:
    return GroqProvider(api_key="test-key", model="test-model")


def test_parse_successful_response():
    resp = httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [
                {"message": {"content": "hello there"}, "finish_reason": "stop"}
            ],
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    result = _provider()._parse_response(resp)
    assert result.content == "hello there"
    assert result.provider == "groq"
    assert result.finish_reason == "stop"


def test_parse_401_raises_auth_error():
    resp = httpx.Response(
        401, json={"error": "unauthorized"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    with pytest.raises(ProviderAuthError):
        _provider()._parse_response(resp)


def test_parse_429_raises_rate_limit_error():
    resp = httpx.Response(
        429, json={"error": "rate limited"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    with pytest.raises(ProviderRateLimitError):
        _provider()._parse_response(resp)


def test_parse_malformed_body_raises_response_error():
    resp = httpx.Response(
        200, json={"unexpected": "shape"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    with pytest.raises(ProviderResponseError):
        _provider()._parse_response(resp)

from __future__ import annotations

import httpx
import pytest

from llm.base import ProviderAuthError, ProviderRateLimitError, ProviderResponseError
from llm.ollama_cloud_provider import OllamaCloudProvider


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

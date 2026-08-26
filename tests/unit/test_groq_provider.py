from __future__ import annotations

import httpx
import pytest
from llm.base import ProviderAuthError, ProviderRateLimitError, ProviderResponseError
from llm.groq_provider import GroqProvider, _parse_groq_duration, _resolve_retry_after


def _provider(**kwargs) -> GroqProvider:
    return GroqProvider(api_key="test-key", model="test-model", **kwargs)


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


# --- Token usage extraction: live-verified shape (Aug 2026) is
# data["usage"] = {"prompt_tokens": ..., "completion_tokens": ...,
# "total_tokens": ..., plus Groq-specific timing fields}.


def test_parse_response_extracts_usage():
    resp = httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 77, "completion_tokens": 56, "total_tokens": 133},
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    result = _provider()._parse_response(resp)
    assert result.usage is not None
    assert result.usage.prompt_tokens == 77
    assert result.usage.completion_tokens == 56
    assert result.usage.total_tokens == 133


def test_parse_response_without_usage_field_leaves_usage_none():
    resp = httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    result = _provider()._parse_response(resp)
    assert result.usage is None


# --- Rate-limit-aware retry: live-observed Groq duration format ("547ms",
# "1.065s", "8m38.4s", ...) on x-ratelimit-reset-tokens/-requests, real bug
# fix motivated by hitting genuine rate limits during heavy live testing.


@pytest.mark.parametrize(
    "value,expected",
    [
        ("547ms", 0.547),
        ("1.065s", 1.065),
        ("2.145s", 2.145),
        ("14m24s", 14 * 60 + 24),
        ("8m38.4s", 8 * 60 + 38.4),
        ("12m57.599s", 12 * 60 + 57.599),
        (None, None),
        ("", None),
        ("garbage", None),
    ],
)
def test_parse_groq_duration(value, expected):
    result = _parse_groq_duration(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_resolve_retry_after_prefers_standard_header():
    resp = httpx.Response(
        429,
        headers={"retry-after": "5", "x-ratelimit-reset-tokens": "1.5s"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    assert _resolve_retry_after(resp) == 5.0


def test_resolve_retry_after_falls_back_to_groq_headers_using_smaller_bucket():
    resp = httpx.Response(
        429,
        headers={
            "x-ratelimit-reset-tokens": "2.145s",
            "x-ratelimit-reset-requests": "8m38.4s",
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    assert _resolve_retry_after(resp) == pytest.approx(2.145)


def test_resolve_retry_after_none_when_no_headers_present():
    resp = httpx.Response(
        429, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )
    assert _resolve_retry_after(resp) is None


def test_parse_429_attaches_retry_after():
    resp = httpx.Response(
        429,
        headers={"x-ratelimit-reset-tokens": "2.145s"},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )
    with pytest.raises(ProviderRateLimitError) as excinfo:
        _provider()._parse_response(resp)
    assert excinfo.value.retry_after == pytest.approx(2.145)


# --- generate()'s retry loop: waits the reported time when short, gives up
# immediately (no wasted wait) when the reported reset is past the cap.


class _FakeAsyncClient:
    def __init__(self, responses):
        # No copy: a fresh client is constructed per retry attempt (real
        # `httpx.AsyncClient` usage), so the queue must be shared across
        # instances to actually advance from one attempt to the next.
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        return self._responses.pop(0)


def _rate_limited_response(reset_tokens: str) -> httpx.Response:
    return httpx.Response(
        429,
        headers={"x-ratelimit-reset-tokens": reset_tokens},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": "test-model", "choices": [{"message": {"content": "ok"}}]},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


@pytest.mark.asyncio
async def test_generate_waits_reported_time_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("llm.groq_provider.asyncio.sleep", fake_sleep)

    responses = [_rate_limited_response("1.5s"), _ok_response()]
    monkeypatch.setattr(
        "llm.groq_provider.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(responses)
    )

    result = await _provider().generate([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert sleeps == [pytest.approx(1.5)]


@pytest.mark.asyncio
async def test_generate_gives_up_immediately_when_reset_exceeds_cap(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr("llm.groq_provider.asyncio.sleep", fake_sleep)

    # Reset is 10 minutes away — far past the wait cap. Only one call should
    # ever be made; generate() must raise instead of sleeping 10 minutes.
    responses = [_rate_limited_response("10m0s")]
    monkeypatch.setattr(
        "llm.groq_provider.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(responses)
    )

    with pytest.raises(ProviderRateLimitError):
        await _provider().generate([{"role": "user", "content": "hi"}])
    assert sleeps == []  # never waited — gave up on Groq immediately

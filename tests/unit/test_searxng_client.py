from __future__ import annotations

import httpx
import pytest
from web.search import SearXNGClient, SearXNGUnavailableError


def _client() -> SearXNGClient:
    return SearXNGClient(base_url="http://localhost:8080")


def test_parse_successful_response():
    resp = httpx.Response(
        200,
        json={
            "results": [
                {"title": "LangGraph docs", "url": "https://example.com/a", "content": "snippet a"},
                {"title": "Other", "url": "https://example.com/b", "content": "snippet b"},
            ]
        },
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )
    results = _client()._parse_response(resp, max_results=8)
    assert len(results) == 2
    assert results[0].title == "LangGraph docs"
    assert results[0].url == "https://example.com/a"
    assert results[0].snippet == "snippet a"


def test_parse_respects_max_results():
    items = [{"title": f"r{i}", "url": f"https://x/{i}", "content": ""} for i in range(10)]
    resp = httpx.Response(
        200,
        json={"results": items},
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )
    results = _client()._parse_response(resp, max_results=3)
    assert len(results) == 3


def test_parse_non_200_raises_unavailable():
    resp = httpx.Response(
        500, text="internal error",
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )
    with pytest.raises(SearXNGUnavailableError):
        _client()._parse_response(resp, max_results=8)


def test_parse_non_json_raises_unavailable_with_hint():
    resp = httpx.Response(
        200, text="<html>not json</html>",
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )
    with pytest.raises(SearXNGUnavailableError, match="json"):
        _client()._parse_response(resp, max_results=8)


def test_parse_empty_results():
    resp = httpx.Response(
        200, json={"results": []},
        request=httpx.Request("GET", "http://localhost:8080/search"),
    )
    assert _client()._parse_response(resp, max_results=8) == []


@pytest.mark.asyncio
async def test_search_connection_error_raises_unavailable(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    with pytest.raises(SearXNGUnavailableError, match="Could not connect"):
        await _client().search("test query")


@pytest.mark.asyncio
async def test_search_timeout_raises_unavailable(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    with pytest.raises(SearXNGUnavailableError, match="timed out"):
        await _client().search("test query")

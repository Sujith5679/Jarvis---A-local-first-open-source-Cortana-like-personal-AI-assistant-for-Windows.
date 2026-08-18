from __future__ import annotations

import pytest
from tools.web_reader import open_webpage_handler
from tools.web_search import web_search_handler
from web.crawler import FetchError
from web.search import SearchResult, SearXNGUnavailableError


@pytest.mark.asyncio
async def test_web_search_empty_query_returns_no_results(real_db):
    result = await web_search_handler("   ")
    assert result["results"] == []


@pytest.mark.asyncio
async def test_web_search_gracefully_degrades_when_searxng_unreachable(real_db):
    """SearXNG genuinely isn't running in this dev environment — this is a
    real (not mocked) end-to-end test of spec.md §32's graceful-degradation
    requirement: 'Explain that web search is temporarily unavailable while
    local features remain available.'"""
    result = await web_search_handler("anything")
    assert "error" in result
    assert "unavailable" in result["error"].lower()
    assert "local" in result["error"].lower()


@pytest.mark.asyncio
async def test_web_search_success(real_db, monkeypatch):
    async def fake_search(self, query, max_results=8):
        return [SearchResult(title="Result A", url="https://a.example", snippet="snippet a")]

    monkeypatch.setattr("web.search.SearXNGClient.search", fake_search)

    result = await web_search_handler("langgraph updates")
    assert result["results"] == [
        {"title": "Result A", "url": "https://a.example", "snippet": "snippet a"}
    ]


@pytest.mark.asyncio
async def test_web_search_propagates_unavailable_as_error(real_db, monkeypatch):
    async def fake_search(self, query, max_results=8):
        raise SearXNGUnavailableError("boom")

    monkeypatch.setattr("web.search.SearXNGClient.search", fake_search)
    result = await web_search_handler("x")
    assert "error" in result


@pytest.mark.asyncio
async def test_open_webpage_rejects_non_http_url():
    result = await open_webpage_handler("not-a-url")
    assert "error" in result


@pytest.mark.asyncio
async def test_open_webpage_success(monkeypatch):
    async def fake_fetch(url, **kw):
        return "<html><body><article><p>Real article content here.</p></article></body></html>"

    monkeypatch.setattr("tools.web_reader.fetch_html", fake_fetch)

    result = await open_webpage_handler("https://example.com/article")
    assert "error" not in result
    assert result["domain"] == "example.com"
    assert "Real article content" in result["content"]
    assert result["retrieved_at"]


@pytest.mark.asyncio
async def test_open_webpage_fetch_error_returns_error_dict(monkeypatch):
    async def fake_fetch(url, **kw):
        raise FetchError("could not connect")

    monkeypatch.setattr("tools.web_reader.fetch_html", fake_fetch)

    result = await open_webpage_handler("https://unreachable.example")
    assert "error" in result

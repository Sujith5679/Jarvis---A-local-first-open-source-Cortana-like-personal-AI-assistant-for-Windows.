from __future__ import annotations

import httpx
import pytest
from web import crawler
from web.crawler import FetchError, fetch_html


@pytest.fixture(autouse=True)
def _clear_cache():
    crawler._cache.clear()
    yield
    crawler._cache.clear()


class _FakeResponse:
    def __init__(
        self,
        status_code=200,
        text="<html><body>hi</body></html>",
        content_type="text/html",
    ):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}


def _fake_client(get_impl):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            return await get_impl(*a, **kw)
    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_fetch_html_success(monkeypatch):
    async def get_impl(*a, **kw):
        return _FakeResponse(text="<html><body>content</body></html>")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(get_impl))
    html = await fetch_html("https://example.com", use_cache=False)
    assert "content" in html


@pytest.mark.asyncio
async def test_fetch_html_caches_result(monkeypatch):
    calls = {"n": 0}

    async def get_impl(*a, **kw):
        calls["n"] += 1
        return _FakeResponse(text="<html><body>cached content</body></html>")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(get_impl))
    await fetch_html("https://example.com/cached")
    await fetch_html("https://example.com/cached")
    assert calls["n"] == 1  # second call served from cache


@pytest.mark.asyncio
async def test_fetch_html_connection_error(monkeypatch):
    class _FakeAsyncClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    with pytest.raises(FetchError, match="Could not connect"):
        await fetch_html("https://example.com", use_cache=False)


@pytest.mark.asyncio
async def test_fetch_html_http_error_status(monkeypatch):
    async def get_impl(*a, **kw):
        return _FakeResponse(status_code=404, text="not found")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(get_impl))
    with pytest.raises(FetchError, match="404"):
        await fetch_html("https://example.com/missing", use_cache=False)


@pytest.mark.asyncio
async def test_fetch_html_rejects_non_html_content_type(monkeypatch):
    async def get_impl(*a, **kw):
        return _FakeResponse(content_type="application/pdf")

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(get_impl))
    with pytest.raises(FetchError, match="not an HTML page"):
        await fetch_html("https://example.com/file.pdf", use_cache=False)


@pytest.mark.asyncio
async def test_fetch_html_rejects_oversized_response(monkeypatch):
    from config.defaults import DEFAULT_WEB_MAX_RESPONSE_BYTES

    async def get_impl(*a, **kw):
        return _FakeResponse(text="x" * (DEFAULT_WEB_MAX_RESPONSE_BYTES + 1))

    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(get_impl))
    with pytest.raises(FetchError, match="too large"):
        await fetch_html("https://example.com/huge", use_cache=False)

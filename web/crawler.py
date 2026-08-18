"""Web page fetching (spec.md §23) with a simple in-memory TTL cache
(spec.md §44 — "Cache web fetches with TTL"; entries just expire on their
own, matching "invalidated when source content changes" closely enough for
short-lived web content without needing a persistent staleness signal).
"""

from __future__ import annotations

import time

import httpx
from config.defaults import (
    DEFAULT_WEB_CACHE_TTL_SECONDS,
    DEFAULT_WEB_FETCH_TIMEOUT_SECONDS,
    DEFAULT_WEB_MAX_RESPONSE_BYTES,
)

USER_AGENT = "JarvisAssistant/0.1 (local personal assistant; not a bulk crawler)"


class FetchError(Exception):
    pass


class _TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: str) -> None:
        self._store[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


_cache = _TTLCache(DEFAULT_WEB_CACHE_TTL_SECONDS)


async def fetch_html(
    url: str,
    *,
    timeout: float = DEFAULT_WEB_FETCH_TIMEOUT_SECONDS,
    use_cache: bool = True,
) -> str:
    if use_cache:
        cached = _cache.get(url)
        if cached is not None:
            return cached

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.ConnectError as exc:
        raise FetchError(f"Could not connect to {url}: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise FetchError(f"Request to {url} timed out: {exc}") from exc

    if resp.status_code >= 400:
        raise FetchError(f"{url} returned HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type:
        raise FetchError(f"{url} is not an HTML page (content-type: {content_type or 'unknown'})")

    if len(resp.content) > DEFAULT_WEB_MAX_RESPONSE_BYTES:
        raise FetchError(f"{url} response too large ({len(resp.content)} bytes)")

    html = resp.text
    if use_cache:
        _cache.set(url, html)
    return html

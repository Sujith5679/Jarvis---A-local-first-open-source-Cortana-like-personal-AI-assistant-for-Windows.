"""SearXNG web search client (spec.md §23).

Uses SearXNG's JSON search API (`GET {SEARXNG_URL}/search?format=json`).
Self-hosted SearXNG instances disable the `json` output format by default —
add `json` to the `formats` list in the instance's `settings.yml` for this
to work (see README).

Every failure mode collapses into `SearXNGUnavailableError` so callers
(`tools/web_search.py`) can degrade gracefully — spec.md §32: "Explain that
web search is temporarily unavailable while local features remain
available" — rather than crashing the turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from config.defaults import DEFAULT_WEB_FETCH_TIMEOUT_SECONDS, DEFAULT_WEB_SEARCH_MAX_RESULTS
from config.settings import Settings

logger = logging.getLogger("jarvis.web.search")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str | None = None


class SearXNGUnavailableError(Exception):
    pass


class SearXNGClient:
    def __init__(
        self, base_url: str, timeout: float = DEFAULT_WEB_FETCH_TIMEOUT_SECONDS
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(
        self, query: str, max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS
    ) -> list[SearchResult]:
        params = {"q": query, "format": "json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/search", params=params)
        except httpx.ConnectError as exc:
            raise SearXNGUnavailableError(
                f"Could not connect to SearXNG at {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise SearXNGUnavailableError(f"SearXNG request timed out: {exc}") from exc

        return self._parse_response(resp, max_results=max_results)

    def _parse_response(self, resp: httpx.Response, *, max_results: int) -> list[SearchResult]:
        if resp.status_code != 200:
            raise SearXNGUnavailableError(
                f"SearXNG returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise SearXNGUnavailableError(
                "SearXNG did not return JSON — is the 'json' output format enabled in its "
                "settings.yml?"
            ) from exc

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    engine=item.get("engine"),
                )
            )
        return results


def build_default_client(settings: Settings) -> SearXNGClient:
    return SearXNGClient(base_url=settings.searxng_url)

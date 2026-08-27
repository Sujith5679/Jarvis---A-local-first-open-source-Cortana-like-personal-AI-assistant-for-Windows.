"""`web_search` tool (spec.md §23) — LOW risk, no confirmation.

Returns titles/URLs/snippets only, never full page content (that's
open_webpage's job) — "never return more data than required" (§18's rule
applies here too).

This is also the one trigger point for SearXNG's lazy auto-start (see
web/searxng_process.py's module docstring) — a session that never calls
this tool never spawns SearXNG at all, even with SEARXNG_AUTOSTART=true.
"""

from __future__ import annotations

from typing import Any

from config.defaults import DEFAULT_WEB_SEARCH_MAX_RESULTS
from config.settings import get_settings
from web.search import SearXNGUnavailableError, build_default_client
from web.searxng_process import get_searxng_manager

from tools.registry import Tool, ToolMetadata


async def web_search_handler(
    query: str, max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"results": []}

    await get_searxng_manager().ensure_started()

    client = build_default_client(get_settings())
    try:
        results = await client.search(query, max_results=max_results)
    except SearXNGUnavailableError as exc:
        return {
            "error": (
                f"Web search is temporarily unavailable ({exc}). Local features "
                "(files, notes, tasks, reminders) still work."
            )
        }

    return {
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results]
    }


WEB_SEARCH = Tool(
    metadata=ToolMetadata(
        name="web_search",
        description=(
            "Search the web via the user's local SearXNG instance. Returns titles, URLs, and "
            "snippets only — use open_webpage to read a specific result's full content. Use "
            "only for current/external information; prefer search_files for the user's own "
            "documents, and don't search the web if local sources already answer the question."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=20.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": DEFAULT_WEB_SEARCH_MAX_RESULTS},
        },
        "required": ["query"],
    },
    handler=web_search_handler,
)


def register(registry) -> None:
    registry.register(WEB_SEARCH)

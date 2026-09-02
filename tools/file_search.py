"""`search_files` tool (spec.md §18) — LOW risk, no confirmation.

Returns only ranked snippets, never full document contents ("The tool must
never return more data than required" — §18). Use `read_file` to pull more
of a specific result.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from config.defaults import DEFAULT_FINAL_TOP_K
from rag.hybrid_retriever import HybridRetriever, build_default_hybrid_retriever

from tools.registry import Tool, ToolMetadata

SNIPPET_MAX_CHARS = 300


@lru_cache(maxsize=1)
def _get_retriever() -> HybridRetriever:
    # Cached: building this loads the local embedding model, which is not free.
    return build_default_hybrid_retriever()


def invalidate_cache() -> None:
    """Drop the cached retriever so the next search rebuilds it (and reloads
    the FAISS index from disk). Must be called after any reindex that runs
    through a *different* VectorStore instance than the cached one — e.g. a
    folder added via the UI — since a VectorStore loads its index into
    memory once and does not watch the file for external changes."""
    _get_retriever.cache_clear()


def _snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


async def search_files_handler(query: str, top_k: int = DEFAULT_FINAL_TOP_K) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"results": []}

    retriever = _get_retriever()
    results = retriever.retrieve(query, final_top_k=top_k)

    return {
        "results": [
            {
                "document_id": str(r.document_id),
                "filename": r.filename,
                "path": r.path,
                # When reranking ran, results are ordered by rerank_score, not
                # the fusion score - show whichever one actually produced this
                # order, so the displayed number is never out of step with it.
                "score": round(r.rerank_score if r.rerank_score is not None else r.score, 4),
                "snippet": _snippet(r.text),
                "page": r.page,
                "section": r.section,
            }
            for r in results
        ]
    }


TOOL = Tool(
    metadata=ToolMetadata(
        name="search_files",
        description=(
            "Search the user's locally indexed personal files (documents, notes) using "
            "hybrid keyword + semantic search. Returns ranked snippets with citations "
            "(filename, path, page). Prefer this over read_file for open-ended questions."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=10.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language search query."},
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return.",
                "default": DEFAULT_FINAL_TOP_K,
            },
        },
        "required": ["query"],
    },
    handler=search_files_handler,
)


def register(registry) -> None:
    registry.register(TOOL)

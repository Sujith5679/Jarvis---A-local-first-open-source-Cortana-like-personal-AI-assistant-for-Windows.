"""SQLite FTS5 keyword retrieval (spec.md §16).

The FTS5 index itself (`document_chunks_fts`) and its sync triggers live in
`storage/migrations.py`; this module only queries it. Chunk inserts/deletes
happen through normal `document_chunks` writes (see `rag/ingestion.py`) and
the triggers keep the index current automatically.
"""

from __future__ import annotations

import sqlite3

from config.defaults import DEFAULT_TOP_K_KEYWORD
from storage.database import get_connection


def _build_match_query(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Each token is wrapped as its own quoted phrase (safe against FTS5's
    special characters) and OR'd together, favoring recall — hybrid ranking
    downstream is what narrows results back down.
    """
    tokens = [t for t in query.split() if t.strip()]
    if not tokens:
        return '""'
    escaped = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens]
    return " OR ".join(escaped)


def search(
    query: str,
    top_k: int = DEFAULT_TOP_K_KEYWORD,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """Return up to `top_k` chunks matching `query`, each with a `bm25_score`
    (lower is better — SQLite FTS5's bm25() convention) plus chunk/document
    metadata needed for citations."""
    match_query = _build_match_query(query)
    sql = """
        SELECT
            dc.id AS chunk_id, dc.document_id, dc.chunk_index, dc.text,
            dc.page, dc.section,
            d.path, d.filename, d.source_type,
            bm25(document_chunks_fts) AS bm25_score
        FROM document_chunks_fts
        JOIN document_chunks dc ON dc.id = document_chunks_fts.rowid
        JOIN documents d ON d.id = dc.document_id
        WHERE document_chunks_fts MATCH ?
        ORDER BY bm25_score
        LIMIT ?
    """

    def _run(c: sqlite3.Connection) -> list[dict]:
        try:
            rows = c.execute(sql, (match_query, top_k)).fetchall()
        except sqlite3.OperationalError:
            # Malformed MATCH expression (e.g. only stopword-like tokens) —
            # treat as "no keyword matches" rather than failing the request.
            return []
        return [dict(row) for row in rows]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

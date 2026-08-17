"""Hybrid keyword + vector retrieval and ranking (spec.md §16).

Merges SQLite FTS5 keyword hits with FAISS vector hits, min-max normalizes
each score set into [0, 1] within the candidate pool, and combines them with
configurable weights. Every parameter here is a tunable
(config.defaults / future retrieval-eval-driven overrides), never hard-coded
at the call site.

This module is the stable interface a reranker (V2, `rag/reranker.py`) slots
into later — it would take `retrieve()`'s candidate list and reorder it,
without any caller of `HybridRetriever.retrieve()` needing to change.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from config.defaults import (
    DEFAULT_FINAL_TOP_K,
    DEFAULT_KEYWORD_WEIGHT,
    DEFAULT_MINIMUM_SCORE,
    DEFAULT_SEMANTIC_WEIGHT,
    DEFAULT_TOP_K_KEYWORD,
    DEFAULT_TOP_K_VECTOR,
)
from storage.database import get_connection

from rag import keyword_store
from rag.embeddings import EmbeddingProvider, get_default_embedding_provider
from rag.vector_store import VectorStore, get_default_vector_store


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    path: str
    filename: str
    source_type: str
    text: str
    score: float
    page: int | None = None
    section: str | None = None
    keyword_score: float | None = None
    semantic_score: float | None = None


def _normalize(scores: dict[int, float], *, invert: bool = False) -> dict[int, float]:
    """Min-max normalize into [0, 1]. `invert=True` for metrics where lower is
    better (FTS5's bm25())."""
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return dict.fromkeys(scores, 1.0)
    if invert:
        return {k: (hi - v) / (hi - lo) for k, v in scores.items()}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _fetch_chunk_metadata(ids: list[int], conn: sqlite3.Connection) -> dict[int, dict]:
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT dc.id AS chunk_id, dc.document_id, dc.chunk_index, dc.text,
               dc.page, dc.section, d.path, d.filename, d.source_type
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    return {row["chunk_id"]: dict(row) for row in rows}


class HybridRetriever:
    def __init__(self, embedding_provider: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def retrieve(
        self,
        query: str,
        *,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
        semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
        top_k_keyword: int = DEFAULT_TOP_K_KEYWORD,
        top_k_vector: int = DEFAULT_TOP_K_VECTOR,
        final_top_k: int = DEFAULT_FINAL_TOP_K,
        minimum_score: float = DEFAULT_MINIMUM_SCORE,
        conn: sqlite3.Connection | None = None,
    ) -> list[RetrievedChunk]:
        def _run(c: sqlite3.Connection) -> list[RetrievedChunk]:
            keyword_hits = keyword_store.search(query, top_k=top_k_keyword, conn=c)
            keyword_scores = {row["chunk_id"]: row["bm25_score"] for row in keyword_hits}
            metadata_by_id = {row["chunk_id"]: row for row in keyword_hits}

            semantic_scores: dict[int, float] = {}
            if query.strip():
                query_vector = self.embedding_provider.embed([query])[0]
                vector_hits = self.vector_store.search(query_vector, top_k=top_k_vector)
                semantic_scores = dict(vector_hits)

            kw_norm = _normalize(keyword_scores, invert=True)
            sem_norm = _normalize(semantic_scores, invert=False)

            all_ids = set(keyword_scores) | set(semantic_scores)
            missing_ids = [i for i in all_ids if i not in metadata_by_id]
            if missing_ids:
                metadata_by_id.update(_fetch_chunk_metadata(missing_ids, c))

            results: list[RetrievedChunk] = []
            for chunk_id in all_ids:
                meta = metadata_by_id.get(chunk_id)
                if meta is None:
                    # Stale FAISS entry for a chunk that no longer exists in
                    # SQLite (e.g. removed by a reindex) — skip rather than error.
                    continue
                kw = kw_norm.get(chunk_id, 0.0)
                sem = sem_norm.get(chunk_id, 0.0)
                score = keyword_weight * kw + semantic_weight * sem
                if score < minimum_score:
                    continue
                results.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        document_id=meta["document_id"],
                        path=meta["path"],
                        filename=meta["filename"],
                        source_type=meta["source_type"],
                        text=meta["text"],
                        page=meta.get("page"),
                        section=meta.get("section"),
                        score=score,
                        keyword_score=keyword_scores.get(chunk_id),
                        semantic_score=semantic_scores.get(chunk_id),
                    )
                )

            results.sort(key=lambda r: r.score, reverse=True)
            return results[:final_top_k]

        if conn is not None:
            return _run(conn)
        with get_connection() as c:
            return _run(c)


def build_default_hybrid_retriever() -> HybridRetriever:
    embedding_provider = get_default_embedding_provider()
    vector_store = get_default_vector_store(dimension=embedding_provider.dimension)
    return HybridRetriever(embedding_provider=embedding_provider, vector_store=vector_store)

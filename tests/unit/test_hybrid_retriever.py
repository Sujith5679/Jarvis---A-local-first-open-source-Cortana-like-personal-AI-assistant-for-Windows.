from __future__ import annotations

from datetime import UTC, datetime

from rag.chunking import Chunk
from rag.hybrid_retriever import HybridRetriever
from rag.vector_store import VectorStore
from storage.repositories import documents as documents_repo

DIM = 3


class _FakeEmbeddings:
    """Deterministic fake: embeds a query/text to a fixed vector by keyword,
    so tests can control semantic similarity precisely."""

    dimension = DIM

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping

    def embed(self, texts):
        return [self.mapping.get(t, [0, 0, 0]) for t in texts]


def _seed_chunk(conn, *, filename: str, text: str) -> int:
    now = datetime.now(UTC).isoformat()
    doc_id = documents_repo.upsert_document(
        path=f"C:/fake/{filename}", filename=filename, source_type="txt",
        folder_id=None, content_hash="h", modified_at=now, status="indexed", conn=conn,
    )
    ids = documents_repo.insert_chunks(doc_id, [Chunk(text=text, chunk_index=0)], conn=conn)
    return ids[0]


def test_keyword_only_ranking(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        keyword_chunk_id = _seed_chunk(conn, filename="a.txt", text="fraud detection approach")
        other_chunk_id = _seed_chunk(conn, filename="b.txt", text="unrelated grocery list")

    embeddings = _FakeEmbeddings({"fraud detection": [0, 0, 0]})  # no semantic signal
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)

    results = retriever.retrieve("fraud detection", keyword_weight=1.0, semantic_weight=0.0)
    assert results[0].chunk_id == keyword_chunk_id
    assert results[0].score > 0
    ids = [r.chunk_id for r in results]
    assert other_chunk_id not in ids or results[-1].chunk_id == other_chunk_id


def test_semantic_only_ranking(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        semantic_chunk_id = _seed_chunk(conn, filename="a.txt", text="completely different words")
        _seed_chunk(conn, filename="b.txt", text="also completely different words")

    embeddings = _FakeEmbeddings({"query": [1, 0, 0]})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    vector_store.add(ids=[semantic_chunk_id], vectors=[[1, 0, 0]])

    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)
    results = retriever.retrieve("query", keyword_weight=0.0, semantic_weight=1.0)

    assert len(results) == 1
    assert results[0].chunk_id == semantic_chunk_id
    assert results[0].semantic_score is not None


def test_minimum_score_filters_low_relevance(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_chunk(conn, filename="a.txt", text="fraud detection approach")

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)

    results = retriever.retrieve(
        "fraud detection", keyword_weight=1.0, semantic_weight=0.0, minimum_score=1.5
    )
    assert results == []


def test_final_top_k_limits_results(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        for i in range(5):
            _seed_chunk(conn, filename=f"doc{i}.txt", text="shared searchable keyword")

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)

    results = retriever.retrieve("shared searchable keyword", final_top_k=2)
    assert len(results) == 2


# --- Reranking (rag/reranker.py) --------------------------------------------


class _FakeReranker:
    """Deterministic fake: scores a passage by how many times a marker
    substring appears in it, so tests can force the cross-encoder to
    disagree with the fusion ranking and prove the override actually wins."""

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        return [float(p.count(self.marker)) for p in passages]


def test_reranker_can_override_fusion_ranking(real_db, tmp_path):
    """Fusion (keyword-only here) ranks 'a' above 'b'; the fake reranker
    scores by a marker only 'b' contains - final order must follow the
    reranker, proving it actually runs and actually reorders."""
    from storage.database import get_connection

    with get_connection() as conn:
        chunk_a = _seed_chunk(conn, filename="a.txt", text="shared searchable keyword alpha")
        chunk_b = _seed_chunk(
            conn, filename="b.txt", text="shared searchable keyword ZZZMARKER"
        )

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    reranker = _FakeReranker(marker="ZZZMARKER")
    retriever = HybridRetriever(
        embedding_provider=embeddings, vector_store=vector_store, reranker=reranker
    )

    # Sanity check: without reranking, "a" (shorter/more exact bm25 match)
    # would not necessarily already be ordered the way the marker demands.
    results = retriever.retrieve(
        "shared searchable keyword", keyword_weight=1.0, semantic_weight=0.0
    )
    assert results[0].chunk_id == chunk_b
    assert results[0].rerank_score == 1.0
    assert results[1].chunk_id == chunk_a
    assert results[1].rerank_score == 0.0
    assert reranker.calls  # actually invoked


def test_rerank_false_skips_reranker(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_chunk(conn, filename="a.txt", text="fraud detection approach")

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    reranker = _FakeReranker(marker="ZZZMARKER")
    retriever = HybridRetriever(
        embedding_provider=embeddings, vector_store=vector_store, reranker=reranker
    )

    results = retriever.retrieve("fraud detection", rerank=False)
    assert results[0].rerank_score is None
    assert reranker.calls == []


def test_no_reranker_configured_leaves_rerank_score_none(real_db, tmp_path):
    """Every existing caller/test that doesn't pass a reranker (the default)
    must keep working exactly as before - this is the backward-compat case."""
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_chunk(conn, filename="a.txt", text="fraud detection approach")

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)

    results = retriever.retrieve("fraud detection")
    assert results[0].rerank_score is None


def test_rerank_candidate_pool_limits_what_reranker_sees(real_db, tmp_path):
    from storage.database import get_connection

    with get_connection() as conn:
        for i in range(5):
            _seed_chunk(conn, filename=f"doc{i}.txt", text="shared searchable keyword")

    embeddings = _FakeEmbeddings({})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    reranker = _FakeReranker(marker="ZZZMARKER")
    retriever = HybridRetriever(
        embedding_provider=embeddings, vector_store=vector_store, reranker=reranker
    )

    retriever.retrieve(
        "shared searchable keyword", final_top_k=2, rerank_candidate_pool=3
    )
    assert len(reranker.calls[0][1]) == 3  # pool, not all 5 or just final_top_k=2


def test_stale_vector_entry_without_sqlite_row_is_skipped(real_db, tmp_path):
    """A chunk id present in FAISS but deleted from SQLite (e.g. reindex race)
    must be skipped, not crash retrieval."""
    embeddings = _FakeEmbeddings({"query": [1, 0, 0]})
    vector_store = VectorStore(dimension=DIM, index_path=tmp_path / "v.faiss")
    vector_store.add(ids=[9999], vectors=[[1, 0, 0]])  # no matching document_chunks row

    retriever = HybridRetriever(embedding_provider=embeddings, vector_store=vector_store)
    results = retriever.retrieve("query")
    assert results == []

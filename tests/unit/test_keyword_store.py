from __future__ import annotations

from datetime import UTC, datetime

from rag import keyword_store
from rag.chunking import Chunk
from storage.repositories import documents as documents_repo


def _seed_document(conn, *, filename: str, texts: list[str]) -> int:
    now = datetime.now(UTC).isoformat()
    doc_id = documents_repo.upsert_document(
        path=f"C:/fake/{filename}",
        filename=filename,
        source_type="txt",
        folder_id=None,
        content_hash="hash",
        modified_at=now,
        status="indexed",
        conn=conn,
    )
    chunks = [Chunk(text=t, chunk_index=i) for i, t in enumerate(texts)]
    documents_repo.insert_chunks(doc_id, chunks, conn=conn)
    return doc_id


def test_search_finds_matching_chunk(real_db):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_document(
            conn,
            filename="claimsx.txt",
            texts=["The ClaimsX fraud detection approach uses gradient boosting."],
        )
        _seed_document(conn, filename="unrelated.txt", texts=["Grocery list: milk, eggs, bread."])

    results = keyword_store.search("fraud detection")
    assert len(results) == 1
    assert results[0]["filename"] == "claimsx.txt"


def test_search_returns_metadata_for_citations(real_db):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_document(
            conn, filename="report.txt", texts=["Quarterly revenue increased significantly."]
        )

    results = keyword_store.search("revenue")
    assert len(results) == 1
    row = results[0]
    assert row["path"] == "C:/fake/report.txt"
    assert row["source_type"] == "txt"
    assert "chunk_id" in row and "bm25_score" in row


def test_search_no_match_returns_empty(real_db):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_document(conn, filename="report.txt", texts=["Some unrelated content here."])

    assert keyword_store.search("nonexistentxyzterm") == []


def test_search_handles_special_characters_safely(real_db):
    from storage.database import get_connection

    with get_connection() as conn:
        _seed_document(conn, filename="report.txt", texts=["Some content here."])

    # Must not raise even with FTS5-special characters in the query.
    results = keyword_store.search('what about "quotes" and (parens) OR NOT AND?')
    assert isinstance(results, list)

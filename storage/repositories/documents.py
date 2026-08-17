"""Document / document_chunk persistence (spec.md §36).

Chunk deletes here don't touch the FAISS vector store — `rag/ingestion.py`
is responsible for removing the corresponding vector IDs *before* calling
`delete_chunks_for_document`, since only it knows which vector store to
target.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from rag.chunking import Chunk

from storage.database import get_connection


def get_by_path(path: str, conn: sqlite3.Connection | None = None) -> dict | None:
    def _run(c: sqlite3.Connection) -> dict | None:
        row = c.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def upsert_document(
    *,
    path: str,
    filename: str,
    source_type: str,
    folder_id: int | None,
    content_hash: str | None,
    modified_at: str | None,
    status: str,
    error_message: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    now = datetime.now(UTC).isoformat()
    indexed_at = now if status == "indexed" else None

    def _run(c: sqlite3.Connection) -> int:
        existing = c.execute("SELECT id FROM documents WHERE path = ?", (path,)).fetchone()
        if existing:
            c.execute(
                """UPDATE documents SET
                       filename = ?, source_type = ?, folder_id = ?, content_hash = ?,
                       modified_at = ?, status = ?, error_message = ?, indexed_at = ?
                   WHERE id = ?""",
                (
                    filename, source_type, folder_id, content_hash,
                    modified_at, status, error_message, indexed_at, existing["id"],
                ),
            )
            return int(existing["id"])
        cur = c.execute(
            """INSERT INTO documents
                   (folder_id, path, filename, source_type, content_hash, status,
                    error_message, modified_at, indexed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                folder_id, path, filename, source_type, content_hash, status,
                error_message, modified_at, indexed_at, now,
            ),
        )
        return int(cur.lastrowid)

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_document(document_id: int, conn: sqlite3.Connection | None = None) -> None:
    """Deletes the document row; ON DELETE CASCADE removes its document_chunks
    rows (and the FTS triggers remove their FTS entries) automatically."""

    def _run(c: sqlite3.Connection) -> None:
        c.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    if conn is not None:
        _run(conn)
        return
    with get_connection() as c:
        _run(c)


def insert_chunks(
    document_id: int, chunks: list[Chunk], conn: sqlite3.Connection | None = None
) -> list[int]:
    now = datetime.now(UTC).isoformat()

    def _run(c: sqlite3.Connection) -> list[int]:
        ids = []
        for chunk in chunks:
            cur = c.execute(
                """INSERT INTO document_chunks
                       (document_id, chunk_index, text, page, section, vector_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (document_id, chunk.chunk_index, chunk.text, chunk.page, chunk.section, None, now),
            )
            chunk_id = int(cur.lastrowid)
            # vector_id mirrors the row id — see rag/vector_store.py.
            c.execute(
                "UPDATE document_chunks SET vector_id = ? WHERE id = ?", (str(chunk_id), chunk_id)
            )
            ids.append(chunk_id)
        return ids

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def delete_chunks_for_document(
    document_id: int, conn: sqlite3.Connection | None = None
) -> list[int]:
    """Deletes all chunks for a document and returns their (now-stale) ids,
    so the caller can remove the matching vectors from the FAISS index."""

    def _run(c: sqlite3.Connection) -> list[int]:
        rows = c.execute(
            "SELECT id FROM document_chunks WHERE document_id = ?", (document_id,)
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        c.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        return ids

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_all_documents(conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        return [dict(row) for row in c.execute("SELECT * FROM documents").fetchall()]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)


def list_documents_by_status(status: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _run(c: sqlite3.Connection) -> list[dict]:
        return [
            dict(row)
            for row in c.execute("SELECT * FROM documents WHERE status = ?", (status,)).fetchall()
        ]

    if conn is not None:
        return _run(conn)
    with get_connection() as c:
        return _run(c)

"""Indexing pipeline (spec.md §14).

discover -> filter supported -> hash/mtime check (skip unchanged) -> extract
-> chunk -> write to SQLite (FTS5 stays in sync via triggers) + FAISS.

One file failing (parse error, unreadable, permission denied) never aborts
the batch — it's marked `failed` with an error message and the scan
continues (spec.md §32, §14.3's "failed-file queue"). `retry_failed()`
re-attempts those later, e.g. from a tray "Reindex files" action.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from documents.base import DocumentParseError
from documents.registry import get_parser, is_supported
from storage.database import get_connection
from storage.repositories import documents as documents_repo
from storage.repositories import folders as folders_repo

from rag.chunking import chunk_segments
from rag.embeddings import EmbeddingProvider, get_default_embedding_provider
from rag.vector_store import VectorStore, get_default_vector_store

logger = logging.getLogger("jarvis.rag.ingestion")

EXCLUDED_DIR_NAMES = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "$RECYCLE.BIN",
    "System Volume Information",
}


def discover_files(folder_path: str):
    root = Path(folder_path)
    if not root.exists() or not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            yield Path(dirpath) / name


def compute_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def file_modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


@dataclass
class IngestionSummary:
    scanned: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    unsupported: int = 0
    failed: int = 0
    removed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def merge(self, other: IngestionSummary) -> None:
        self.scanned += other.scanned
        self.indexed += other.indexed
        self.skipped_unchanged += other.skipped_unchanged
        self.unsupported += other.unsupported
        self.failed += other.failed
        self.removed += other.removed
        self.failures.extend(other.failures)


class IngestionPipeline:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider or get_default_embedding_provider()
        self.vector_store = vector_store or get_default_vector_store(
            dimension=self.embedding_provider.dimension
        )

    def _index_file(self, path: Path, folder_id: int, conn, *, force: bool) -> str:
        """Returns one of 'indexed' | 'skipped' | 'unsupported' | 'failed'."""
        path_str = str(path)
        existing = documents_repo.get_by_path(path_str, conn=conn)
        extension = path.suffix.lstrip(".").lower() or "unknown"

        try:
            modified_at = file_modified_at(path)
        except OSError as exc:
            logger.warning("Could not stat %s: %s", path, exc)
            return "failed"

        if not is_supported(path):
            if not existing or existing["status"] != "unsupported":
                documents_repo.upsert_document(
                    path=path_str, filename=path.name, source_type=extension,
                    folder_id=folder_id, content_hash=None, modified_at=modified_at,
                    status="unsupported", conn=conn,
                )
            return "unsupported"

        try:
            content_hash = compute_content_hash(path)
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
            documents_repo.upsert_document(
                path=path_str, filename=path.name, source_type=extension,
                folder_id=folder_id, content_hash=None, modified_at=modified_at,
                status="failed", error_message=str(exc), conn=conn,
            )
            return "failed"

        if (
            not force
            and existing
            and existing["status"] == "indexed"
            and existing["content_hash"] == content_hash
        ):
            return "skipped"

        parser = get_parser(path)
        assert parser is not None  # is_supported() already confirmed this
        try:
            extracted = parser.extract(path)
        except DocumentParseError as exc:
            logger.warning("Failed to parse %s: %s", path, exc)
            documents_repo.upsert_document(
                path=path_str, filename=path.name, source_type=extension,
                folder_id=folder_id, content_hash=content_hash, modified_at=modified_at,
                status="failed", error_message=str(exc), conn=conn,
            )
            return "failed"

        chunks = chunk_segments(extracted.segments)
        document_id = documents_repo.upsert_document(
            path=path_str, filename=path.name, source_type=extracted.source_type,
            folder_id=folder_id, content_hash=content_hash, modified_at=modified_at,
            status="indexed", conn=conn,
        )

        old_chunk_ids = documents_repo.delete_chunks_for_document(document_id, conn=conn)
        if old_chunk_ids:
            self.vector_store.remove(old_chunk_ids)

        if chunks:
            new_ids = documents_repo.insert_chunks(document_id, chunks, conn=conn)
            vectors = self.embedding_provider.embed([c.text for c in chunks])
            self.vector_store.add(new_ids, vectors)

        return "indexed"

    def sync_folder(self, folder: dict, *, force: bool = False) -> IngestionSummary:
        summary = IngestionSummary()
        with get_connection() as conn:
            for path in discover_files(folder["path"]):
                summary.scanned += 1
                try:
                    result = self._index_file(path, folder["id"], conn, force=force)
                except Exception as exc:  # defensive: one bad file must never abort the batch
                    logger.exception("Unexpected error indexing %s", path)
                    result = "failed"
                    summary.failures.append((str(path), str(exc)))

                if result == "indexed":
                    summary.indexed += 1
                elif result == "skipped":
                    summary.skipped_unchanged += 1
                elif result == "unsupported":
                    summary.unsupported += 1
                elif result == "failed":
                    summary.failed += 1
                    if not summary.failures or summary.failures[-1][0] != str(path):
                        summary.failures.append((str(path), "see logs"))
        return summary

    def remove_deleted_files(self) -> int:
        removed = 0
        with get_connection() as conn:
            docs = documents_repo.list_all_documents(conn=conn)
        for doc in docs:
            if Path(doc["path"]).exists():
                continue
            with get_connection() as conn:
                chunk_ids = documents_repo.delete_chunks_for_document(doc["id"], conn=conn)
                if chunk_ids:
                    self.vector_store.remove(chunk_ids)
                documents_repo.delete_document(doc["id"], conn=conn)
            removed += 1
        return removed

    def sync_all_enabled_folders(self, *, force: bool = False) -> IngestionSummary:
        total = IngestionSummary()
        for folder in folders_repo.list_folders(enabled_only=True):
            total.merge(self.sync_folder(folder, force=force))
        total.removed = self.remove_deleted_files()
        return total

    def retry_failed(self) -> IngestionSummary:
        with get_connection() as conn:
            failed_docs = documents_repo.list_documents_by_status("failed", conn=conn)

        summary = IngestionSummary()
        for doc in failed_docs:
            summary.scanned += 1
            with get_connection() as conn:
                try:
                    result = self._index_file(
                        Path(doc["path"]), doc["folder_id"], conn, force=True
                    )
                except Exception as exc:
                    logger.exception("Retry failed for %s", doc["path"])
                    result = "failed"
                    summary.failures.append((doc["path"], str(exc)))

            if result == "indexed":
                summary.indexed += 1
            elif result == "failed":
                summary.failed += 1
        return summary

from __future__ import annotations

import time

from rag.embeddings import get_default_embedding_provider
from rag.ingestion import IngestionPipeline
from rag.vector_store import get_default_vector_store
from storage.repositories import documents as documents_repo
from storage.repositories import folders as folders_repo


def _make_pipeline() -> IngestionPipeline:
    embedding_provider = get_default_embedding_provider()
    vector_store = get_default_vector_store(dimension=embedding_provider.dimension)
    return IngestionPipeline(embedding_provider=embedding_provider, vector_store=vector_store)


def test_sync_indexes_supported_files_and_skips_unsupported(real_db, tmp_path):
    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    (folder_dir / "a.txt").write_text("Hello world about fraud detection.", encoding="utf-8")
    (folder_dir / "unsupported.exe").write_bytes(b"\x00\x01")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    summary = pipeline.sync_all_enabled_folders()

    assert summary.indexed == 1
    assert summary.unsupported == 1
    assert summary.failed == 0

    docs = documents_repo.list_all_documents()
    statuses = {d["filename"]: d["status"] for d in docs}
    assert statuses["a.txt"] == "indexed"
    assert statuses["unsupported.exe"] == "unsupported"

    doc = documents_repo.get_by_path(str((folder_dir / "a.txt").resolve()))
    assert pipeline.vector_store.size >= 1
    assert doc is not None


def test_unchanged_file_is_skipped_on_second_sync(real_db):
    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    (folder_dir / "a.txt").write_text("Some stable content.", encoding="utf-8")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    first = pipeline.sync_all_enabled_folders()
    assert first.indexed == 1

    second = pipeline.sync_all_enabled_folders()
    assert second.indexed == 0
    assert second.skipped_unchanged == 1


def test_modified_file_is_reindexed(real_db):
    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    target = folder_dir / "a.txt"
    target.write_text("Original content.", encoding="utf-8")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    pipeline.sync_all_enabled_folders()
    doc_before = documents_repo.get_by_path(str(target.resolve()))

    time.sleep(0.05)
    target.write_text("Completely different updated content.", encoding="utf-8")
    summary = pipeline.sync_all_enabled_folders()

    assert summary.indexed == 1
    doc_after = documents_repo.get_by_path(str(target.resolve()))
    assert doc_after["content_hash"] != doc_before["content_hash"]


def test_deleted_file_is_removed_from_index(real_db):
    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    target = folder_dir / "a.txt"
    target.write_text("Temporary content.", encoding="utf-8")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    pipeline.sync_all_enabled_folders()
    assert documents_repo.get_by_path(str(target.resolve())) is not None
    size_before = pipeline.vector_store.size

    target.unlink()
    summary = pipeline.sync_all_enabled_folders()

    assert summary.removed == 1
    assert documents_repo.get_by_path(str(target.resolve())) is None
    assert pipeline.vector_store.size < size_before


def test_corrupt_file_marked_failed_and_others_still_indexed(real_db):
    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    (folder_dir / "good.txt").write_text("Perfectly fine content.", encoding="utf-8")
    (folder_dir / "bad.pdf").write_bytes(b"not actually a pdf")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    summary = pipeline.sync_all_enabled_folders()

    assert summary.indexed == 1
    assert summary.failed == 1

    bad_doc = documents_repo.get_by_path(str((folder_dir / "bad.pdf").resolve()))
    assert bad_doc["status"] == "failed"
    assert bad_doc["error_message"]

    good_doc = documents_repo.get_by_path(str((folder_dir / "good.txt").resolve()))
    assert good_doc["status"] == "indexed"


def test_retry_failed_reattempts_after_fix(real_db):
    import pymupdf

    folder_dir = real_db.data_dir / "src"
    folder_dir.mkdir()
    bad_path = folder_dir / "bad.pdf"
    bad_path.write_bytes(b"not actually a pdf")
    folders_repo.add_folder(str(folder_dir))

    pipeline = _make_pipeline()
    pipeline.sync_all_enabled_folders()
    assert documents_repo.get_by_path(str(bad_path.resolve()))["status"] == "failed"

    # Retrying an unfixed file should still report failure.
    still_broken = pipeline.retry_failed()
    assert still_broken.scanned == 1
    assert still_broken.failed == 1
    assert documents_repo.get_by_path(str(bad_path.resolve()))["status"] == "failed"

    # "Fix" the file in place with a genuinely valid PDF. Built fully in memory
    # and written via Path.write_bytes() (not PyMuPDF's own save()) — saving
    # directly over this exact path right after a failed open() hits a
    # Windows-only PyMuPDF file-lock quirk.
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Now valid content.")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    bad_path.write_bytes(pdf_bytes)

    fixed_summary = pipeline.retry_failed()
    assert fixed_summary.indexed == 1
    assert documents_repo.get_by_path(str(bad_path.resolve()))["status"] == "indexed"

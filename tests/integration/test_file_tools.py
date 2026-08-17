from __future__ import annotations

import pytest
from tools.file_reader import read_file_handler
from tools.file_search import search_files_handler


@pytest.mark.asyncio
async def test_search_files_finds_indexed_content(indexed_sample_folder):
    _folder, _pipeline, files = indexed_sample_folder

    result = await search_files_handler("fraud detection approach")

    assert result["results"], "expected at least one match"
    top = result["results"][0]
    assert top["filename"] == "claimsx_report.txt"
    assert str(files["claims"]) == top["path"] or files["claims"].name in top["path"]
    assert "fraud" in top["snippet"].lower()
    assert 0.0 <= top["score"] <= 1.0 + 1e-6


@pytest.mark.asyncio
async def test_search_files_ranks_relevant_query_higher_than_unrelated(indexed_sample_folder):
    # With only two documents indexed, semantic search always returns its
    # nearest neighbor even for a wildly unrelated query — there's no
    # absolute "no match" the way FTS5 has. What must hold is that a query
    # actually about the document scores it higher than an unrelated one does.
    relevant = await search_files_handler("fraud detection approach")
    unrelated = await search_files_handler("nonexistent quantum teleportation matrix")

    def _score_for(results, filename):
        return next((r["score"] for r in results if r["filename"] == filename), 0.0)

    relevant_score = _score_for(relevant["results"], "claimsx_report.txt")
    unrelated_score = _score_for(unrelated["results"], "claimsx_report.txt")
    assert relevant_score > unrelated_score


@pytest.mark.asyncio
async def test_search_files_empty_query_returns_no_results(indexed_sample_folder):
    result = await search_files_handler("   ")
    assert result["results"] == []


@pytest.mark.asyncio
async def test_read_file_returns_content_for_indexed_path(indexed_sample_folder):
    _folder, _pipeline, files = indexed_sample_folder
    result = await read_file_handler(str(files["claims"]))
    assert "error" not in result
    assert "fraud detection" in result["content"].lower()
    assert result["filename"] == "claimsx_report.txt"


@pytest.mark.asyncio
async def test_read_file_rejects_path_outside_indexed_folders(indexed_sample_folder, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret stuff", encoding="utf-8")
    result = await read_file_handler(str(outside))
    assert "error" in result
    assert "outside" in result["error"].lower() or "allowed" in result["error"].lower()


@pytest.mark.asyncio
async def test_read_file_rejects_unindexed_path_inside_folder(indexed_sample_folder):
    folder, _pipeline, _files = indexed_sample_folder
    never_indexed = f"{folder['path']}\\never_written.txt"
    result = await read_file_handler(never_indexed)
    assert "error" in result

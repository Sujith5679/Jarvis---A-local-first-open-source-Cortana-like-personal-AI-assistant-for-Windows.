from __future__ import annotations

import pytest
from storage.repositories import folders as folders_repo
from tools.file_writer import write_file_handler


@pytest.mark.asyncio
async def test_rejects_path_outside_indexed_folders(real_db, tmp_path):
    outside = tmp_path / "not_indexed"
    outside.mkdir()
    result = await write_file_handler(str(outside / "note.txt"), "hello")
    assert "error" in result
    assert "indexed" in result["error"].lower()


@pytest.mark.asyncio
async def test_creates_new_file_with_content(real_db, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))

    target = folder / "todo.txt"
    result = await write_file_handler(str(target), "buy milk\nwalk the dog")

    assert "error" not in result
    assert result["created"] is True
    assert result["overwritten"] is False
    assert target.read_text(encoding="utf-8") == "buy milk\nwalk the dog"


@pytest.mark.asyncio
async def test_refuses_overwrite_without_flag(real_db, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))
    target = folder / "todo.txt"
    target.write_text("original", encoding="utf-8")

    result = await write_file_handler(str(target), "replacement")
    assert "error" in result
    assert "overwrite" in result["error"].lower()
    assert target.read_text(encoding="utf-8") == "original"  # untouched


@pytest.mark.asyncio
async def test_overwrites_with_flag(real_db, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))
    target = folder / "todo.txt"
    target.write_text("original", encoding="utf-8")

    result = await write_file_handler(str(target), "replacement", overwrite=True)
    assert result["overwritten"] is True
    assert result["created"] is False
    assert target.read_text(encoding="utf-8") == "replacement"


@pytest.mark.asyncio
async def test_creates_missing_subdirectories_within_indexed_folder(real_db, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    folders_repo.add_folder(str(folder))

    target = folder / "archive" / "2026" / "todo.txt"
    result = await write_file_handler(str(target), "content")
    assert "error" not in result
    assert target.exists()


@pytest.mark.asyncio
async def test_rejects_writing_over_a_directory(real_db, tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "subdir").mkdir()
    folders_repo.add_folder(str(folder))

    result = await write_file_handler(str(folder / "subdir"), "content")
    assert "error" in result

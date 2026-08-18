from __future__ import annotations

import pytest
from storage.repositories import folders as folders_repo
from tools.file_listing import list_folder_handler, list_indexed_folders_handler


@pytest.mark.asyncio
async def test_list_indexed_folders_returns_enabled_folders(real_db, tmp_path):
    folder_a = tmp_path / "music"
    folder_a.mkdir()
    folder_b = tmp_path / "docs"
    folder_b.mkdir()
    folders_repo.add_folder(str(folder_a))
    added_id = folders_repo.add_folder(str(folder_b))
    folders_repo.remove_folder(added_id)  # disabled, must not appear

    result = await list_indexed_folders_handler()
    paths = [f["path"] for f in result["folders"]]
    assert str(folder_a.resolve()) in paths
    assert str(folder_b.resolve()) not in paths


@pytest.mark.asyncio
async def test_list_indexed_folders_empty_when_none_added(real_db):
    result = await list_indexed_folders_handler()
    assert result["folders"] == []


@pytest.mark.asyncio
async def test_list_folder_error_message_points_to_list_indexed_folders(real_db, tmp_path):
    outside = tmp_path / "not_indexed"
    outside.mkdir()
    result = await list_folder_handler(str(outside))
    assert "list_indexed_folders" in result["error"]


@pytest.mark.asyncio
async def test_rejects_folder_outside_allowlist(real_db, tmp_path):
    outside = tmp_path / "not_indexed"
    outside.mkdir()
    result = await list_folder_handler(str(outside))
    assert "error" in result
    assert "indexed" in result["error"].lower()


@pytest.mark.asyncio
async def test_counts_top_level_files_and_folders(real_db, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "a.mp3").write_bytes(b"x")
    (folder / "b.mp3").write_bytes(b"x")
    (folder / "c.flac").write_bytes(b"x")
    (folder / "subalbum").mkdir()
    (folder / "subalbum" / "d.mp3").write_bytes(b"x")  # not counted (non-recursive)

    folders_repo.add_folder(str(folder))

    result = await list_folder_handler(str(folder))
    assert "error" not in result
    assert result["total_files"] == 3
    assert result["total_folders"] == 1
    assert result["by_extension"] == {"mp3": 2, "flac": 1}
    assert result["recursive"] is False


@pytest.mark.asyncio
async def test_recursive_includes_subfolder_contents(real_db, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "a.mp3").write_bytes(b"x")
    (folder / "subalbum").mkdir()
    (folder / "subalbum" / "b.mp3").write_bytes(b"x")
    (folder / "subalbum" / "nested").mkdir()
    (folder / "subalbum" / "nested" / "c.mp3").write_bytes(b"x")

    folders_repo.add_folder(str(folder))

    result = await list_folder_handler(str(folder), recursive=True)
    assert result["total_files"] == 3
    assert result["total_folders"] == 2


@pytest.mark.asyncio
async def test_nonexistent_folder_inside_allowlist_returns_error(real_db, tmp_path):
    parent = tmp_path / "indexed_parent"
    parent.mkdir()
    folders_repo.add_folder(str(parent))

    result = await list_folder_handler(str(parent / "does_not_exist"))
    assert "error" in result


@pytest.mark.asyncio
async def test_file_path_instead_of_folder_returns_error(real_db, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "a.mp3").write_bytes(b"x")
    folders_repo.add_folder(str(folder))

    result = await list_folder_handler(str(folder / "a.mp3"))
    assert "error" in result


@pytest.mark.asyncio
async def test_entries_are_relative_paths(real_db, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    (folder / "song.mp3").write_bytes(b"x")
    folders_repo.add_folder(str(folder))

    result = await list_folder_handler(str(folder))
    assert result["entries"] == ["song.mp3"]

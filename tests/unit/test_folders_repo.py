from __future__ import annotations

from pathlib import Path

from storage.repositories import folders as folders_repo


def test_add_and_list_folder(real_db, tmp_path):
    target = tmp_path / "Documents"
    target.mkdir()
    folders_repo.add_folder(str(target))

    folders = folders_repo.list_folders(enabled_only=True)
    assert len(folders) == 1
    assert Path(folders[0]["path"]) == target.resolve()


def test_remove_folder_disables_not_deletes(real_db, tmp_path):
    target = tmp_path / "Documents"
    target.mkdir()
    folder_id = folders_repo.add_folder(str(target))
    folders_repo.remove_folder(folder_id)

    assert folders_repo.list_folders(enabled_only=True) == []
    assert len(folders_repo.list_folders(enabled_only=False)) == 1


def test_path_inside_indexed_folder_is_allowed(real_db, tmp_path):
    target = tmp_path / "Documents"
    target.mkdir()
    (target / "report.pdf").write_text("x")
    folders_repo.add_folder(str(target))

    assert folders_repo.is_path_within_indexed_folders(str(target / "report.pdf")) is True


def test_path_outside_indexed_folder_is_denied(real_db, tmp_path):
    allowed = tmp_path / "Documents"
    allowed.mkdir()
    folders_repo.add_folder(str(allowed))

    other = tmp_path / "Secrets"
    other.mkdir()
    (other / "credentials.txt").write_text("x")

    assert folders_repo.is_path_within_indexed_folders(str(other / "credentials.txt")) is False


def test_path_traversal_outside_indexed_folder_is_denied(real_db, tmp_path):
    allowed = tmp_path / "Documents"
    allowed.mkdir()
    folders_repo.add_folder(str(allowed))

    traversal_path = str(allowed / ".." / "Secrets" / "credentials.txt")
    assert folders_repo.is_path_within_indexed_folders(traversal_path) is False


def test_disabled_folder_no_longer_allowed(real_db, tmp_path):
    target = tmp_path / "Documents"
    target.mkdir()
    (target / "report.pdf").write_text("x")
    folder_id = folders_repo.add_folder(str(target))
    folders_repo.remove_folder(folder_id)

    assert folders_repo.is_path_within_indexed_folders(str(target / "report.pdf")) is False

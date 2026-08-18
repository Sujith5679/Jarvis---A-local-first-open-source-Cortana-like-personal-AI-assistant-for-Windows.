from __future__ import annotations

from storage.repositories import notes as notes_repo


def test_create_and_get_note(real_db):
    note_id = notes_repo.create_note(title="Groceries", content="milk, eggs", tags=["home"])
    note = notes_repo.get_note(note_id)
    assert note["title"] == "Groceries"
    assert note["content"] == "milk, eggs"
    assert note["tags"] == ["home"]
    assert note["archived"] is False


def test_search_notes_matches_title_and_content(real_db):
    notes_repo.create_note(title="ClaimsX ideas", content="add reranking")
    notes_repo.create_note(title="Unrelated", content="buy milk")

    results = notes_repo.search_notes("reranking")
    assert len(results) == 1
    assert results[0]["title"] == "ClaimsX ideas"

    results_by_title = notes_repo.search_notes("ClaimsX")
    assert len(results_by_title) == 1


def test_search_excludes_archived_by_default(real_db):
    note_id = notes_repo.create_note(title="Old note", content="stale content")
    notes_repo.archive_note(note_id)

    assert notes_repo.search_notes("stale") == []
    assert len(notes_repo.search_notes("stale", include_archived=True)) == 1


def test_update_note_partial_fields(real_db):
    note_id = notes_repo.create_note(title="Title", content="Content")
    ok = notes_repo.update_note(note_id, content="New content")
    assert ok is True

    note = notes_repo.get_note(note_id)
    assert note["title"] == "Title"  # unchanged
    assert note["content"] == "New content"


def test_update_note_missing_returns_false(real_db):
    assert notes_repo.update_note(999, content="x") is False


def test_delete_note(real_db):
    note_id = notes_repo.create_note(title="Temp", content="to be deleted")
    assert notes_repo.delete_note(note_id) is True
    assert notes_repo.get_note(note_id) is None
    assert notes_repo.delete_note(note_id) is False


def test_list_notes_excludes_archived(real_db):
    id1 = notes_repo.create_note(title="A", content="a")
    id2 = notes_repo.create_note(title="B", content="b")
    notes_repo.archive_note(id2)

    active = notes_repo.list_notes()
    assert [n["id"] for n in active] == [id1]

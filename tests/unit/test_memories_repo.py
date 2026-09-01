from __future__ import annotations

import pytest
from storage.repositories import memories as memories_repo


def test_create_and_get_memory(real_db):
    memory_id = memories_repo.create_memory("User prefers metric units.", memory_type="preference")
    m = memories_repo.get_memory(memory_id)
    assert m["content"] == "User prefers metric units."
    assert m["memory_type"] == "preference"
    assert m["deletable"] is True
    assert m["metadata"] == {}


def test_create_memory_default_type_is_knowledge(real_db):
    memory_id = memories_repo.create_memory("The user's dog is named Rex.")
    assert memories_repo.get_memory(memory_id)["memory_type"] == "knowledge"


def test_create_memory_rejects_invalid_type(real_db):
    with pytest.raises(ValueError):
        memories_repo.create_memory("x", memory_type="not_a_real_type")


def test_create_memory_stores_metadata(real_db):
    memory_id = memories_repo.create_memory("x", metadata={"source": "conversation_5"})
    assert memories_repo.get_memory(memory_id)["metadata"] == {"source": "conversation_5"}


def test_get_missing_memory_returns_none(real_db):
    assert memories_repo.get_memory(999) is None


def test_list_memories_newest_first(real_db):
    memories_repo.create_memory("first")
    memories_repo.create_memory("second")
    memories_repo.create_memory("third")

    results = memories_repo.list_memories()
    assert [m["content"] for m in results] == ["third", "second", "first"]


def test_list_memories_respects_limit(real_db):
    for i in range(5):
        memories_repo.create_memory(f"fact {i}")

    results = memories_repo.list_memories(limit=2)
    assert len(results) == 2


def test_list_memories_filters_by_type(real_db):
    memories_repo.create_memory("pref one", memory_type="preference")
    memories_repo.create_memory("knowledge one", memory_type="knowledge")

    results = memories_repo.list_memories(memory_type="preference")
    assert len(results) == 1
    assert results[0]["content"] == "pref one"


def test_search_memories_matches_content(real_db):
    memories_repo.create_memory("The user loves hiking.")
    memories_repo.create_memory("The user's favorite color is blue.")

    results = memories_repo.search_memories("hiking")
    assert len(results) == 1
    assert "hiking" in results[0]["content"]


def test_search_memories_no_match_returns_empty(real_db):
    memories_repo.create_memory("something")
    assert memories_repo.search_memories("nonexistent") == []


def test_delete_memory_removes_it(real_db):
    memory_id = memories_repo.create_memory("temporary fact")
    assert memories_repo.delete_memory(memory_id) is True
    assert memories_repo.get_memory(memory_id) is None


def test_delete_missing_memory_returns_false(real_db):
    assert memories_repo.delete_memory(999) is False


def test_delete_non_deletable_memory_is_refused(real_db):
    """Directly flips deletable=0 to simulate a future non-user-facing
    memory - delete_memory must never remove one even given its exact id."""
    memory_id = memories_repo.create_memory("system fact")
    from storage.database import get_connection

    with get_connection() as conn:
        conn.execute("UPDATE memories SET deletable = 0 WHERE id = ?", (memory_id,))

    assert memories_repo.delete_memory(memory_id) is False
    assert memories_repo.get_memory(memory_id) is not None

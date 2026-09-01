from __future__ import annotations

import pytest
from storage.repositories import memories as memories_repo
from tools import memory


@pytest.mark.asyncio
async def test_remember_fact_creates_memory(real_db):
    result = await memory.remember_fact_handler("User prefers dark mode.")
    assert result["content"] == "User prefers dark mode."
    assert result["memory_type"] == "knowledge"
    assert memories_repo.get_memory(result["memory_id"]) is not None


@pytest.mark.asyncio
async def test_remember_fact_rejects_empty_content(real_db):
    result = await memory.remember_fact_handler("   ")
    assert "error" in result


@pytest.mark.asyncio
async def test_remember_fact_rejects_invalid_memory_type(real_db):
    result = await memory.remember_fact_handler("x", memory_type="nonsense")
    assert "error" in result


@pytest.mark.asyncio
async def test_remember_fact_accepts_preference_type(real_db):
    result = await memory.remember_fact_handler("Likes tea over coffee.", memory_type="preference")
    assert result["memory_type"] == "preference"


@pytest.mark.asyncio
async def test_recall_facts_without_query_lists_recent(real_db):
    await memory.remember_fact_handler("fact one")
    await memory.remember_fact_handler("fact two")

    result = await memory.recall_facts_handler()
    contents = {r["content"] for r in result["results"]}
    assert contents == {"fact one", "fact two"}


@pytest.mark.asyncio
async def test_recall_facts_with_query_searches(real_db):
    await memory.remember_fact_handler("The user enjoys chess.")
    await memory.remember_fact_handler("The user's birthday is in June.")

    result = await memory.recall_facts_handler(query="chess")
    assert len(result["results"]) == 1
    assert "chess" in result["results"][0]["content"]


@pytest.mark.asyncio
async def test_forget_fact_deletes_memory(real_db):
    created = await memory.remember_fact_handler("temporary")
    result = await memory.forget_fact_handler(created["memory_id"])
    assert result["forgotten"] is True
    assert memories_repo.get_memory(created["memory_id"]) is None


@pytest.mark.asyncio
async def test_forget_fact_missing_id_returns_error(real_db):
    result = await memory.forget_fact_handler(999)
    assert "error" in result


# --- Tool metadata: risk levels match notes.py's precedent -----------------


def test_remember_and_recall_do_not_require_confirmation():
    assert memory.REMEMBER_FACT.metadata.requires_confirmation is False
    assert memory.RECALL_FACTS.metadata.requires_confirmation is False


def test_forget_requires_confirmation_and_is_high_risk():
    assert memory.FORGET_FACT.metadata.requires_confirmation is True
    assert memory.FORGET_FACT.metadata.risk_level == "high"


def test_register_adds_all_three_tools():
    from tools.registry import ToolRegistry

    registry = ToolRegistry()
    memory.register(registry)
    names = {t.name for t in registry.all()}
    assert names == {"remember_fact", "recall_facts", "forget_fact"}

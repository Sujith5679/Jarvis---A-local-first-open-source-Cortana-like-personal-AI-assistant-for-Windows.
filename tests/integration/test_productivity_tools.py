from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tools.notes import (
    create_note_handler,
    delete_note_handler,
    search_notes_handler,
    update_note_handler,
)
from tools.reminders import create_reminder_handler, list_reminders_handler
from tools.tasks import (
    complete_task_handler,
    create_task_handler,
    delete_task_handler,
    list_tasks_handler,
)


@pytest.mark.asyncio
async def test_create_and_search_note(real_db):
    result = await create_note_handler(content="Add reranking to ClaimsX", title="ClaimsX TODO")
    assert "error" not in result
    assert result["note_id"] > 0

    search = await search_notes_handler("reranking")
    assert len(search["results"]) == 1
    assert search["results"][0]["title"] == "ClaimsX TODO"


@pytest.mark.asyncio
async def test_create_note_rejects_empty_content(real_db):
    result = await create_note_handler(content="   ")
    assert "error" in result


@pytest.mark.asyncio
async def test_update_note_handler_missing_id(real_db):
    result = await update_note_handler(note_id=999, content="x")
    assert "error" in result


@pytest.mark.asyncio
async def test_delete_note_handler(real_db):
    created = await create_note_handler(content="temp")
    result = await delete_note_handler(note_id=created["note_id"])
    assert result == {"note_id": created["note_id"], "deleted": True}

    missing = await delete_note_handler(note_id=created["note_id"])
    assert "error" in missing


@pytest.mark.asyncio
async def test_create_list_complete_delete_task(real_db):
    created = await create_task_handler(title="Submit report", priority="high")
    assert "error" not in created

    listed = await list_tasks_handler(status="open")
    assert any(t["id"] == created["task_id"] for t in listed["results"])

    completed = await complete_task_handler(task_id=created["task_id"])
    assert completed["status"] == "completed"

    deleted = await delete_task_handler(task_id=created["task_id"])
    assert deleted["deleted"] is True


@pytest.mark.asyncio
async def test_create_task_invalid_priority(real_db):
    result = await create_task_handler(title="x", priority="urgent")
    assert "error" in result


@pytest.mark.asyncio
async def test_create_and_list_reminder(real_db):
    trigger = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    created = await create_reminder_handler(title="Submit report", trigger_at=trigger)
    assert "error" not in created

    listed = await list_reminders_handler(status="pending")
    assert any(r["id"] == created["reminder_id"] for r in listed["results"])


@pytest.mark.asyncio
async def test_create_reminder_requires_trigger_at(real_db):
    result = await create_reminder_handler(title="x", trigger_at="")
    assert "error" in result

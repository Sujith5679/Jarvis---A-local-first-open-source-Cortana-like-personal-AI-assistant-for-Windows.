from __future__ import annotations

import pytest
from storage.repositories import tasks as tasks_repo


def test_create_and_get_task(real_db):
    task_id = tasks_repo.create_task(title="Submit report", priority="high", due_at="2026-08-20")
    task = tasks_repo.get_task(task_id)
    assert task["title"] == "Submit report"
    assert task["priority"] == "high"
    assert task["status"] == "open"
    assert task["due_at"] == "2026-08-20"


def test_invalid_priority_rejected(real_db):
    with pytest.raises(ValueError):
        tasks_repo.create_task(title="x", priority="urgent")


def test_list_tasks_filters_by_status(real_db):
    open_id = tasks_repo.create_task(title="Open task")
    done_id = tasks_repo.create_task(title="Done task")
    tasks_repo.complete_task(done_id)

    open_tasks = tasks_repo.list_tasks(status="open")
    assert [t["id"] for t in open_tasks] == [open_id]

    completed_tasks = tasks_repo.list_tasks(status="completed")
    assert [t["id"] for t in completed_tasks] == [done_id]


def test_complete_task_sets_completed_at(real_db):
    task_id = tasks_repo.create_task(title="x")
    assert tasks_repo.complete_task(task_id) is True
    task = tasks_repo.get_task(task_id)
    assert task["status"] == "completed"
    assert task["completed_at"] is not None


def test_update_task_partial_fields(real_db):
    task_id = tasks_repo.create_task(title="Original", priority="low")
    ok = tasks_repo.update_task(task_id, priority="high")
    assert ok is True
    task = tasks_repo.get_task(task_id)
    assert task["title"] == "Original"
    assert task["priority"] == "high"


def test_update_task_invalid_status_rejected(real_db):
    task_id = tasks_repo.create_task(title="x")
    with pytest.raises(ValueError):
        tasks_repo.update_task(task_id, status="bogus")


def test_delete_task(real_db):
    task_id = tasks_repo.create_task(title="Temp")
    assert tasks_repo.delete_task(task_id) is True
    assert tasks_repo.get_task(task_id) is None
    assert tasks_repo.delete_task(task_id) is False

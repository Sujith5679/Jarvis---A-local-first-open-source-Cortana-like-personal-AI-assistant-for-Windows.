"""Task tools (spec.md §21). create/list/update/complete = LOW; delete = HIGH
(requires confirmation, per spec.md §21's "Delete task with confirmation")."""

from __future__ import annotations

from typing import Any

from storage.repositories import tasks as tasks_repo

from tools.registry import Tool, ToolMetadata


async def create_task_handler(
    title: str,
    description: str | None = None,
    priority: str = "normal",
    due_at: str | None = None,
) -> dict[str, Any]:
    if not title or not title.strip():
        return {"error": "Task title cannot be empty."}
    try:
        task_id = tasks_repo.create_task(
            title=title, description=description, priority=priority, due_at=due_at
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"task_id": task_id, "title": title, "status": "open", "priority": priority}


async def list_tasks_handler(status: str | None = None) -> dict[str, Any]:
    return {"results": tasks_repo.list_tasks(status=status)}


async def update_task_handler(
    task_id: int,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    try:
        ok = tasks_repo.update_task(
            task_id,
            title=title,
            description=description,
            priority=priority,
            due_at=due_at,
            status=status,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    if not ok:
        return {"error": f"No task found with id {task_id}."}
    return {"task_id": task_id, "updated": True}


async def complete_task_handler(task_id: int) -> dict[str, Any]:
    ok = tasks_repo.complete_task(task_id)
    if not ok:
        return {"error": f"No task found with id {task_id}."}
    return {"task_id": task_id, "status": "completed"}


async def delete_task_handler(task_id: int) -> dict[str, Any]:
    ok = tasks_repo.delete_task(task_id)
    if not ok:
        return {"error": f"No task found with id {task_id}."}
    return {"task_id": task_id, "deleted": True}


CREATE_TASK = Tool(
    metadata=ToolMetadata(
        name="create_task",
        description="Create a new task with optional description, priority, and due date.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"},
            "due_at": {"type": "string", "description": "ISO 8601 datetime, if any."},
        },
        "required": ["title"],
    },
    handler=create_task_handler,
)

LIST_TASKS = Tool(
    metadata=ToolMetadata(
        name="list_tasks",
        description="List the user's tasks, optionally filtered by status.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["open", "in_progress", "completed", "cancelled"],
            }
        },
    },
    handler=list_tasks_handler,
)

UPDATE_TASK = Tool(
    metadata=ToolMetadata(
        name="update_task",
        description="Update an existing task's fields.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "due_at": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["open", "in_progress", "completed", "cancelled"],
            },
        },
        "required": ["task_id"],
    },
    handler=update_task_handler,
)

COMPLETE_TASK = Tool(
    metadata=ToolMetadata(
        name="complete_task",
        description="Mark a task as completed.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
    handler=complete_task_handler,
)

DELETE_TASK = Tool(
    metadata=ToolMetadata(
        name="delete_task",
        description="Permanently delete a task by id. This cannot be undone.",
        requires_confirmation=True,
        risk_level="high",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
    handler=delete_task_handler,
)


def register(registry) -> None:
    registry.register(CREATE_TASK)
    registry.register(LIST_TASKS)
    registry.register(UPDATE_TASK)
    registry.register(COMPLETE_TASK)
    registry.register(DELETE_TASK)

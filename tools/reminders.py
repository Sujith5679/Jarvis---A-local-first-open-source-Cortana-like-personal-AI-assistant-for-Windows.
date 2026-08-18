"""Reminder tools (spec.md §22). All LOW risk — spec lists create/list/
complete/dismiss for reminders, with no explicit delete requirement (unlike
notes/tasks), so none of these require confirmation."""

from __future__ import annotations

from typing import Any

from storage.repositories import reminders as reminders_repo

from tools.registry import Tool, ToolMetadata


async def create_reminder_handler(
    title: str,
    trigger_at: str,
    description: str | None = None,
    recurrence: str | None = None,
) -> dict[str, Any]:
    if not title or not title.strip():
        return {"error": "Reminder title cannot be empty."}
    if not trigger_at or not trigger_at.strip():
        return {"error": "trigger_at is required (an ISO 8601 datetime)."}
    try:
        reminder_id = reminders_repo.create_reminder(
            title=title, trigger_at=trigger_at, description=description, recurrence=recurrence
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "reminder_id": reminder_id,
        "title": title,
        "trigger_at": trigger_at,
        "recurrence": recurrence,
    }


async def list_reminders_handler(status: str | None = None) -> dict[str, Any]:
    return {"results": reminders_repo.list_reminders(status=status)}


async def complete_reminder_handler(reminder_id: int) -> dict[str, Any]:
    ok = reminders_repo.complete_reminder(reminder_id)
    if not ok:
        return {"error": f"No reminder found with id {reminder_id}."}
    return {"reminder_id": reminder_id, "status": "completed"}


async def dismiss_reminder_handler(reminder_id: int) -> dict[str, Any]:
    ok = reminders_repo.dismiss_reminder(reminder_id)
    if not ok:
        return {"error": f"No reminder found with id {reminder_id}."}
    return {"reminder_id": reminder_id, "status": "dismissed"}


CREATE_REMINDER = Tool(
    metadata=ToolMetadata(
        name="create_reminder",
        description=(
            "Create a reminder that fires a notification at a specific time. "
            "trigger_at must be a full ISO 8601 datetime resolved from the user's request "
            "against the current date/time given in your instructions."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "trigger_at": {"type": "string", "description": "ISO 8601 datetime with timezone."},
            "description": {"type": "string"},
            "recurrence": {"type": "string", "enum": ["daily", "weekly"]},
        },
        "required": ["title", "trigger_at"],
    },
    handler=create_reminder_handler,
)

LIST_REMINDERS = Tool(
    metadata=ToolMetadata(
        name="list_reminders",
        description="List the user's reminders, optionally filtered by status.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "fired", "dismissed", "completed"]}
        },
    },
    handler=list_reminders_handler,
)

COMPLETE_REMINDER = Tool(
    metadata=ToolMetadata(
        name="complete_reminder",
        description="Mark a reminder as completed.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"reminder_id": {"type": "integer"}},
        "required": ["reminder_id"],
    },
    handler=complete_reminder_handler,
)

DISMISS_REMINDER = Tool(
    metadata=ToolMetadata(
        name="dismiss_reminder",
        description="Dismiss a reminder without marking it completed.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"reminder_id": {"type": "integer"}},
        "required": ["reminder_id"],
    },
    handler=dismiss_reminder_handler,
)


def register(registry) -> None:
    registry.register(CREATE_REMINDER)
    registry.register(LIST_REMINDERS)
    registry.register(COMPLETE_REMINDER)
    registry.register(DISMISS_REMINDER)

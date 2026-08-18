"""Note tools (spec.md §20). create/search/update = LOW; delete = HIGH
(requires confirmation, per spec.md §20's "Delete note with confirmation")."""

from __future__ import annotations

from typing import Any

from storage.repositories import notes as notes_repo

from tools.registry import Tool, ToolMetadata


async def create_note_handler(
    content: str, title: str | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    if not content or not content.strip():
        return {"error": "Note content cannot be empty."}
    note_id = notes_repo.create_note(title=title, content=content, tags=tags)
    return {"note_id": note_id, "title": title, "content": content, "tags": tags or []}


async def search_notes_handler(query: str, include_archived: bool = False) -> dict[str, Any]:
    return {"results": notes_repo.search_notes(query, include_archived=include_archived)}


async def update_note_handler(
    note_id: int,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    ok = notes_repo.update_note(note_id, title=title, content=content, tags=tags)
    if not ok:
        return {"error": f"No note found with id {note_id}."}
    return {"note_id": note_id, "updated": True}


async def delete_note_handler(note_id: int) -> dict[str, Any]:
    ok = notes_repo.delete_note(note_id)
    if not ok:
        return {"error": f"No note found with id {note_id}."}
    return {"note_id": note_id, "deleted": True}


CREATE_NOTE = Tool(
    metadata=ToolMetadata(
        name="create_note",
        description="Create a new personal note with optional title and tags.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The note's content."},
            "title": {"type": "string", "description": "Optional short title."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
        },
        "required": ["content"],
    },
    handler=create_note_handler,
)

SEARCH_NOTES = Tool(
    metadata=ToolMetadata(
        name="search_notes",
        description="Search the user's notes by keyword in title or content.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword(s) to search for."},
            "include_archived": {"type": "boolean", "default": False},
        },
        "required": ["query"],
    },
    handler=search_notes_handler,
)

UPDATE_NOTE = Tool(
    metadata=ToolMetadata(
        name="update_note",
        description="Update an existing note's title, content, and/or tags.",
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "integer"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["note_id"],
    },
    handler=update_note_handler,
)

DELETE_NOTE = Tool(
    metadata=ToolMetadata(
        name="delete_note",
        description="Permanently delete a note by id. This cannot be undone.",
        requires_confirmation=True,
        risk_level="high",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"note_id": {"type": "integer"}},
        "required": ["note_id"],
    },
    handler=delete_note_handler,
)


def register(registry) -> None:
    registry.register(CREATE_NOTE)
    registry.register(SEARCH_NOTES)
    registry.register(UPDATE_NOTE)
    registry.register(DELETE_NOTE)

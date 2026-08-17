"""`read_file` tool (spec.md §19) — LOW risk, no confirmation.

Only reads content already indexed from an enabled, allowed folder — never
an arbitrary filesystem path. `security_check()` resolves the path first
(collapsing `..`) before checking it against the indexed-folder allowlist,
so traversal outside the allowlist is rejected (spec.md §38). The agent
should prefer `search_files` and only call this for a specific known
result's page/section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.database import get_connection
from storage.repositories import documents as documents_repo
from storage.repositories import folders as folders_repo

from tools.registry import Tool, ToolMetadata

MAX_CHARS_DEFAULT = 4000
DEFAULT_CHUNK_PREVIEW_LIMIT = 5


async def read_file_handler(
    path: str,
    page: int | None = None,
    section: str | None = None,
    max_chars: int = MAX_CHARS_DEFAULT,
) -> dict[str, Any]:
    if not folders_repo.is_path_within_indexed_folders(path):
        return {"error": "That path is outside JARVIS's allowed indexed folders."}

    resolved_path = str(Path(path).resolve(strict=False))
    doc = documents_repo.get_by_path(resolved_path)
    if not doc or doc["status"] != "indexed":
        return {
            "error": (
                "That file is not currently indexed. Use search_files first, "
                "or ask the user to add/reindex its folder."
            )
        }

    with get_connection() as conn:
        if page is not None:
            rows = conn.execute(
                "SELECT * FROM document_chunks WHERE document_id = ? AND page = ? "
                "ORDER BY chunk_index",
                (doc["id"], page),
            ).fetchall()
        elif section is not None:
            rows = conn.execute(
                "SELECT * FROM document_chunks WHERE document_id = ? AND section = ? "
                "ORDER BY chunk_index",
                (doc["id"], section),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM document_chunks WHERE document_id = ? "
                "ORDER BY chunk_index LIMIT ?",
                (doc["id"], DEFAULT_CHUNK_PREVIEW_LIMIT),
            ).fetchall()

    if not rows:
        return {"error": f"No indexed content found for that location in {doc['filename']}."}

    text_parts: list[str] = []
    total = 0
    truncated = False
    for row in rows:
        text = row["text"]
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                text_parts.append(text[:remaining] + "...")
            truncated = True
            break
        text_parts.append(text)
        total += len(text)
    else:
        truncated = len(rows) == DEFAULT_CHUNK_PREVIEW_LIMIT and page is None and section is None

    return {
        "document_id": str(doc["id"]),
        "filename": doc["filename"],
        "path": doc["path"],
        "page": page,
        "section": section,
        "content": "\n\n".join(text_parts),
        "truncated": truncated,
    }


TOOL = Tool(
    metadata=ToolMetadata(
        name="read_file",
        description=(
            "Read content from a specific already-indexed local file, optionally scoped to a "
            "page or section. Only works for files inside an enabled indexed folder. Prefer "
            "search_files first to find the right file/page."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=10.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full local path to the file."},
            "page": {"type": "integer", "description": "Optional page number (PDF/PPTX)."},
            "section": {"type": "string", "description": "Optional section/sheet/heading name."},
        },
        "required": ["path"],
    },
    handler=read_file_handler,
)


def register(registry) -> None:
    registry.register(TOOL)

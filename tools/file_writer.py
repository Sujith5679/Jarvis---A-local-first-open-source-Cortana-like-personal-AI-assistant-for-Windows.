"""`write_file` tool — creates or overwrites a text file (spec.md §3: notes
should be saveable, and this is also how "open a file and modify it" works:
read_file to get the current content, write_file(..., overwrite=True) to
save the changed version back — no separate edit tool needed).

HIGH risk, ALWAYS requires confirmation — for both a brand-new file and an
overwrite. Unlike search_files/read_file/list_folder (read-only), this
mutates the real filesystem outside JARVIS's own SQLite-backed, audit-
tracked world: there's no built-in undo for a file write the way there is
for e.g. a DB delete. Spec.md §6 explicitly forbids deleting files without
confirmation and §61.13 forbids silently degrading security for
convenience; a same-path overwrite is effectively a partial delete of the
old content, so it gets the same treatment as a fresh write rather than a
lighter one — our confirmation gate is per-tool, not per-call, so there is
no safe way to distinguish "new file" from "overwrite" risk at the
permission-check stage anyway (that happens before the handler runs).

Restricted to already-indexed folders, the same allowlist as read_file
(spec.md §38 default-deny) — JARVIS does not gain a new, wider filesystem
footprint just because this is a write instead of a read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.repositories import folders as folders_repo

from tools.registry import Tool, ToolMetadata


async def write_file_handler(path: str, content: str, overwrite: bool = False) -> dict[str, Any]:
    if not folders_repo.is_path_within_indexed_folders(path):
        return {
            "error": (
                f"'{path}' isn't inside a currently indexed folder, so JARVIS can't write "
                "there. Call list_indexed_folders to see allowed locations, or ask the user "
                "to add the target folder via Settings > Manage Folders."
            )
        }

    resolved = Path(path).resolve(strict=False)
    if resolved.is_dir():
        return {"error": f"'{resolved}' is a folder, not a file path."}

    existed_before = resolved.exists()
    if existed_before and not overwrite:
        return {
            "error": (
                f"'{resolved}' already exists. Pass overwrite=true to replace it, or choose "
                "a different filename."
            )
        }

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"error": f"Could not write '{resolved}': {exc}"}

    return {
        "path": str(resolved),
        "bytes_written": len(content.encode("utf-8")),
        "created": not existed_before,
        "overwritten": existed_before,
    }


WRITE_FILE = Tool(
    metadata=ToolMetadata(
        name="write_file",
        description=(
            "Create a new text file, or overwrite an existing one (overwrite=true), inside an "
            "already-indexed folder. Use this to save a note/generated text as a real file, or "
            "to save back modified content after read_file. This ALWAYS requires the user's "
            "explicit confirmation before anything is written — call it directly, do not ask "
            "the user to confirm in chat text first, the application handles that."
        ),
        requires_confirmation=True,
        risk_level="high",
        timeout_seconds=10.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full path to the file to write."},
            "content": {"type": "string", "description": "Text content to write."},
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": "Must be true to replace an existing file.",
            },
        },
        "required": ["path", "content"],
    },
    handler=write_file_handler,
)


def register(registry) -> None:
    registry.register(WRITE_FILE)

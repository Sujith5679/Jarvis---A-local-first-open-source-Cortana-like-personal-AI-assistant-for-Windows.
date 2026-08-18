"""`list_folder` tool — lists files/subfolders and counts within an indexed
folder (spec.md §3: "Interact with approved Windows functions" /
"Search personal files").

This only ever returns file *names* and counts, never file *content* — that
stays read_file's job. It's still gated behind the same indexed-folder
allowlist as search_files/read_file (spec.md §38 "Allowed reads must be
limited to... indexed folders... Default deny"): browsing an arbitrary path
just because it returns names, not content, would silently widen JARVIS's
file access beyond what the user explicitly granted via §14.1's folder
selection. Unlike search_files/read_file, this does NOT require the folder
to have finished RAG ingestion (no parsing/embedding happens here) — it just
needs to be a currently-enabled indexed folder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.repositories import folders as folders_repo

from tools.registry import Tool, ToolMetadata

logger = logging.getLogger("jarvis.tools.file_listing")

MAX_ENTRIES_RETURNED = 300


def _scan(
    directory: Path,
    root: Path,
    *,
    recursive: bool,
    counts: dict[str, int],
    by_extension: dict[str, int],
    entries: list[str],
) -> None:
    try:
        children = sorted(directory.iterdir())
    except OSError as exc:
        logger.warning("Could not list %s: %s", directory, exc)
        return

    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            counts["folders"] += 1
            if recursive:
                _scan(
                    child, root, recursive=recursive, counts=counts,
                    by_extension=by_extension, entries=entries,
                )
        elif child.is_file():
            counts["files"] += 1
            ext = child.suffix.lower().lstrip(".") or "(no extension)"
            by_extension[ext] = by_extension.get(ext, 0) + 1
            if len(entries) < MAX_ENTRIES_RETURNED:
                entries.append(str(child.relative_to(root)))


async def list_folder_handler(path: str, recursive: bool = False) -> dict[str, Any]:
    if not folders_repo.is_path_within_indexed_folders(path):
        return {
            "error": (
                "That folder isn't in JARVIS's allowed folders. Add it first via "
                "Settings > Manage Folders, then ask again."
            )
        }

    resolved = Path(path).resolve(strict=False)
    if not resolved.exists():
        return {"error": f"Folder does not exist: {resolved}"}
    if not resolved.is_dir():
        return {"error": f"Not a folder: {resolved}"}

    counts = {"files": 0, "folders": 0}
    by_extension: dict[str, int] = {}
    entries: list[str] = []
    _scan(
        resolved, resolved, recursive=recursive,
        counts=counts, by_extension=by_extension, entries=entries,
    )

    return {
        "path": str(resolved),
        "recursive": recursive,
        "total_files": counts["files"],
        "total_folders": counts["folders"],
        "by_extension": by_extension,
        "entries": entries,
        "truncated": counts["files"] > len(entries),
    }


LIST_FOLDER = Tool(
    metadata=ToolMetadata(
        name="list_folder",
        description=(
            "List files and subfolders inside an already-indexed folder, with a total file "
            "count and a breakdown by extension. Use this to answer questions like 'how many "
            "files are in X' or 'what's in this folder' — it does not read file content, only "
            "names/counts (use search_files/read_file for content). Set recursive=true to "
            "include subfolders in the count."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=15.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full path to the folder."},
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "Include subfolders' contents in the count.",
            },
        },
        "required": ["path"],
    },
    handler=list_folder_handler,
)


def register(registry) -> None:
    registry.register(LIST_FOLDER)

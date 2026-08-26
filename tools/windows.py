"""Windows integration tools (spec.md §29, §57 Phase 6): `launch_application`,
`open_file`, `lock_system`.

Security rules, straight from spec.md §29 ("Windows Command Security"):
- Never expose `os.system(user_generated_string)` or any shell as a tool.
- `launch_application` only ever runs an executable from the fixed
  `config.defaults.DEFAULT_APP_ALLOWLIST` map — the LLM picks a *key*
  (e.g. "notepad"), never a raw command string, and `subprocess.Popen`
  is called with a list (no `shell=True`), so there is no string to inject
  into.
- `open_file` reuses the exact same indexed-folder allowlist check as
  `tools/file_reader.py` (`folders_repo.is_path_within_indexed_folders`) —
  it can only open a file JARVIS already knows about from an enabled
  indexed folder, never an arbitrary path.
- `lock_system` takes no arguments at all — there's nothing to allowlist.

All three require user confirmation (spec.md §2.3: "Potentially destructive
or externally consequential operations require confirmation" — launching a
program the user didn't type themselves, or locking their active session,
both qualify) even though none of them are individually irreversible.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
from typing import Any

from config.defaults import DEFAULT_APP_ALLOWLIST
from storage.repositories import folders as folders_repo

from tools.registry import Tool, ToolMetadata

logger = logging.getLogger("jarvis.tools.windows")

LAUNCH_TIMEOUT_SECONDS = 10.0


async def launch_application_handler(application: str) -> dict[str, Any]:
    key = application.strip().lower()
    exe = DEFAULT_APP_ALLOWLIST.get(key)
    if exe is None:
        allowed = ", ".join(sorted(DEFAULT_APP_ALLOWLIST))
        return {
            "error": f"'{application}' is not in the allowed application list. "
            f"Allowed: {allowed}."
        }

    try:
        # No shell, no string interpolation - exactly the allowlisted
        # executable name, resolved via PATH like any normal Windows launch.
        subprocess.Popen([exe])  # noqa: S603 - exe is from the fixed allowlist above
    except OSError as exc:
        return {"error": f"Could not launch {exe}: {exc}"}

    return {"application": key, "executable": exe, "launched": True}


async def open_file_handler(path: str) -> dict[str, Any]:
    if not folders_repo.is_path_within_indexed_folders(path):
        return {"error": "That path is outside JARVIS's allowed indexed folders."}

    if not os.path.exists(path):
        return {"error": f"File not found: {path}"}

    try:
        os.startfile(path)  # noqa: S606 - Windows-only, path already allowlist-checked above
    except OSError as exc:
        return {"error": f"Could not open {path}: {exc}"}

    return {"path": path, "opened": True}


async def lock_system_handler() -> dict[str, Any]:
    try:
        result = ctypes.windll.user32.LockWorkStation()
    except (AttributeError, OSError) as exc:
        return {"error": f"Could not lock the workstation: {exc}"}

    if not result:
        return {"error": "Windows reported LockWorkStation failed."}
    return {"locked": True}


LAUNCH_APPLICATION = Tool(
    metadata=ToolMetadata(
        name="launch_application",
        description=(
            "Launch an application from a fixed allowlist (e.g. notepad, calculator, paint, "
            "wordpad, explorer, snipping tool, task manager, control panel). Cannot run "
            "arbitrary programs or commands."
        ),
        requires_confirmation=True,
        risk_level="medium",
        timeout_seconds=LAUNCH_TIMEOUT_SECONDS,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "Name of the application to launch, e.g. 'notepad'.",
            }
        },
        "required": ["application"],
    },
    handler=launch_application_handler,
)

OPEN_FILE = Tool(
    metadata=ToolMetadata(
        name="open_file",
        description=(
            "Open an already-indexed local file in its default Windows application. Only "
            "works for files inside an enabled indexed folder."
        ),
        requires_confirmation=True,
        risk_level="medium",
        timeout_seconds=LAUNCH_TIMEOUT_SECONDS,
    ),
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Full local path to open."}},
        "required": ["path"],
    },
    handler=open_file_handler,
)

LOCK_SYSTEM = Tool(
    metadata=ToolMetadata(
        name="lock_system",
        description="Lock the Windows session immediately. Interrupts whatever the user is doing.",
        requires_confirmation=True,
        risk_level="high",
        timeout_seconds=5.0,
    ),
    input_schema={"type": "object", "properties": {}},
    handler=lock_system_handler,
)


def register(registry) -> None:
    registry.register(LAUNCH_APPLICATION)
    registry.register(OPEN_FILE)
    registry.register(LOCK_SYSTEM)

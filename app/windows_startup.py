""""Start JARVIS with Windows" preference (spec.md §27), via Windows Task
Scheduler — never the Startup folder or a registry Run key, and never
enabled automatically. This is a Settings-UI-only action (ui/settings.py);
it is NOT an agent tool — letting the LLM register its own auto-start would
be a real privilege-escalation-adjacent surface, unlike the read-only or
explicitly-confirmed tools in tools/windows.py.

Uses `schtasks.exe` (stdlib subprocess, no pywin32 dependency) to create a
per-user logon task that runs `start_jarvis.bat` — the same launcher a
person would double-click, resolving its own directory rather than
depending on the current working directory (spec.md §27).
"""

from __future__ import annotations

import logging
import subprocess

from config.settings import BASE_DIR

logger = logging.getLogger("jarvis.app.windows_startup")

TASK_NAME = "JARVIS_AutoStart"
_LAUNCHER = BASE_DIR / "start_jarvis.bat"


class StartupTaskError(Exception):
    pass


def is_startup_enabled() -> bool:
    """True if the Task Scheduler task exists (regardless of what
    JARVIS_START_ON_BOOT in .env currently says — this checks the actual
    OS-level state, which is the source of truth once a user has toggled it
    in Settings)."""
    result = subprocess.run(  # noqa: S603, S607 - fixed args, no user input
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def enable_startup() -> None:
    """Registers a per-user logon task that runs start_jarvis.bat. Requires
    no admin privileges (/SC ONLOGON with no /RU is the current user)."""
    if not _LAUNCHER.exists():
        raise StartupTaskError(f"Launcher not found: {_LAUNCHER}")

    result = subprocess.run(  # noqa: S603, S607 - fixed args, no user input
        [
            "schtasks", "/Create", "/TN", TASK_NAME,
            "/TR", f'"{_LAUNCHER}"',
            "/SC", "ONLOGON",
            "/RL", "LIMITED",
            "/F",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise StartupTaskError(result.stderr.strip() or result.stdout.strip())
    logger.info("Registered startup task %r -> %s", TASK_NAME, _LAUNCHER)


def disable_startup() -> None:
    """Removes the logon task. A no-op (not an error) if it isn't registered."""
    result = subprocess.run(  # noqa: S603, S607 - fixed args, no user input
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 and "cannot find" not in result.stderr.lower():
        raise StartupTaskError(result.stderr.strip() or result.stdout.strip())
    logger.info("Removed startup task %r (if it existed)", TASK_NAME)

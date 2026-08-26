"""Optional local SearXNG subprocess management (spec.md §23; README's "Web
search" section).

SearXNG lives *outside* the JARVIS repo — a separate checkout with its own
venv, per the README's manual setup. This module never assumes that exists;
auto-start only happens when the user opts in (`SEARXNG_AUTOSTART=true`)
and points `SEARXNG_DIR` at a real checkout. Any missing prerequisite just
skips auto-start and logs why — `web/search.py`'s existing "SearXNG
offline" handling covers the rest, same graceful-degradation rule as every
other optional subsystem (spec.md §32).

Before spawning anything, `start()` checks whether `SEARXNG_URL` is already
reachable (e.g. the user started it manually, or it's already running from
a previous JARVIS session that didn't exit cleanly) and skips spawning if
so — both to avoid a redundant process fighting over the same port, and so
`stop()` never kills an instance JARVIS didn't start itself.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import httpx
from config.defaults import DEFAULT_HEALTH_CHECK_WEB_TIMEOUT_SECONDS
from config.settings import Settings

logger = logging.getLogger("jarvis.web.searxng_process")


class SearXNGProcessManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process: subprocess.Popen | None = None

    def _python_exe(self) -> Path | None:
        if not self.settings.searxng_dir:
            return None
        venv_python = Path(self.settings.searxng_dir) / ".venv" / "Scripts" / "python.exe"
        return venv_python if venv_python.exists() else None

    def _already_reachable(self) -> bool:
        try:
            resp = httpx.get(
                self.settings.searxng_url, timeout=DEFAULT_HEALTH_CHECK_WEB_TIMEOUT_SECONDS
            )
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    def start(self) -> None:
        """No-op unless SEARXNG_AUTOSTART is set. Never raises — a failure
        to start SearXNG must not prevent the rest of JARVIS from
        starting."""
        if not self.settings.searxng_autostart:
            return
        if self._process is not None and self._process.poll() is None:
            return  # already running under our management

        if self._already_reachable():
            logger.info(
                "SearXNG already reachable at %s — not starting another instance.",
                self.settings.searxng_url,
            )
            return

        python_exe = self._python_exe()
        if python_exe is None:
            logger.warning(
                "SEARXNG_AUTOSTART is true but no venv found at %s\\.venv\\Scripts\\python.exe "
                "— skipping auto-start (see README's Web search section for setup).",
                self.settings.searxng_dir,
            )
            return

        try:
            self._process = subprocess.Popen(  # noqa: S603 - fixed args, path from local config
                [str(python_exe), "-m", "searx.webapp"],
                cwd=str(self.settings.searxng_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                "Started SearXNG subprocess (pid=%s) from %s",
                self._process.pid,
                self.settings.searxng_dir,
            )
        except OSError as exc:
            logger.warning("Could not start SearXNG: %s", exc)

    def stop(self) -> None:
        """Only ever terminates a process this manager itself spawned —
        never one it found already running (see `_already_reachable`)."""
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        logger.info("Stopped SearXNG subprocess (pid=%s)", self._process.pid)
        self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

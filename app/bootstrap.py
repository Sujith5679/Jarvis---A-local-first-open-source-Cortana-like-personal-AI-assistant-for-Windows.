"""Startup wiring: config -> logging -> database/migrations -> audit.

`bootstrap()` is the single place that assembles process-wide infrastructure
before anything else (UI, agent, tools) runs. Every later phase hangs its own
startup step off this function rather than duplicating setup logic.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from config.settings import Settings, get_settings
from security.audit import log_event
from storage.database import connect
from storage.migrations import apply_migrations

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _configure_logging(settings: Settings) -> logging.Logger:
    level = getattr(logging, settings.jarvis_log_level.upper(), logging.INFO)
    log_file = settings.logs_dir / "jarvis.log"

    root = logging.getLogger("jarvis")
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    return root


@dataclass
class BootstrapContext:
    settings: Settings
    logger: logging.Logger
    migrations_applied: list[int]


def bootstrap() -> BootstrapContext:
    """Initialize configuration, logging, database schema, and audit logging.

    Idempotent and safe to call once at process start. Returns a context
    object other startup steps (LLM manager, agent graph, UI, scheduler) can
    read from instead of re-deriving settings/logger themselves.
    """
    settings = get_settings()
    logger = _configure_logging(settings)
    logger.info("JARVIS bootstrap starting (data_dir=%s)", settings.data_dir)

    conn = connect()
    try:
        applied = apply_migrations(conn)
        if applied:
            logger.info("Applied database migrations: %s", applied)
        else:
            logger.info("Database schema up to date.")
    finally:
        conn.close()

    log_event(
        "startup",
        status="success",
        result_summary=f"migrations_applied={applied}",
    )

    logger.info("JARVIS bootstrap complete.")
    return BootstrapContext(settings=settings, logger=logger, migrations_applied=applied)

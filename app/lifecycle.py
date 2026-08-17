"""Application lifecycle hooks: shutdown, and (later) startup health checks.

The full subsystem health check (LLM provider, SearXNG, voice, scheduler —
spec.md §50) is built out in Phase 6 once those subsystems exist. For now
this only covers the pieces Phase 0 owns: config and database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from security.audit import log_event
from storage.database import connect

from app.bootstrap import BootstrapContext

logger = logging.getLogger("jarvis.lifecycle")

HealthState = Literal["ok", "offline", "error"]


@dataclass
class HealthCheckResult:
    component: str
    state: HealthState
    detail: str | None = None


def check_database(ctx: BootstrapContext) -> HealthCheckResult:
    try:
        conn = connect(ctx.settings.db_path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return HealthCheckResult("database", "ok")
    except Exception as exc:  # pragma: no cover - defensive
        return HealthCheckResult("database", "error", str(exc))


def check_config(ctx: BootstrapContext) -> HealthCheckResult:
    if not ctx.settings.has_groq() and not ctx.settings.has_ollama_cloud():
        return HealthCheckResult(
            "configuration", "offline", "No LLM provider configured (see .env.example)"
        )
    return HealthCheckResult("configuration", "ok")


def run_health_checks(ctx: BootstrapContext) -> list[HealthCheckResult]:
    """Run the health checks owned by Phase 0. Later phases append their own
    (LLM provider reachability, vector index, SearXNG, voice, scheduler, UI)."""
    results = [check_config(ctx), check_database(ctx)]
    for result in results:
        logger.info("Health check: %s = %s (%s)", result.component, result.state, result.detail)
    return results


def shutdown(ctx: BootstrapContext) -> None:
    """Graceful shutdown hook. Called on normal app exit."""
    logger.info("JARVIS shutting down.")
    log_event("shutdown", status="success")

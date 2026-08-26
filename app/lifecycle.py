"""Application lifecycle hooks: shutdown, and startup health checks
(spec.md §50 — Configuration, Database, Vector index, LLM provider, Web
search, Voice subsystem, Scheduler, UI).

Every check here must stay fast (no heavy model loads, no un-timeboxed
network calls — spec.md §42's startup performance budget) since these all
run synchronously before the UI appears. Failures are always reported, not
raised: spec.md §50 is explicit that a degraded subsystem must show as a
warning without preventing unrelated functionality from working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx
from config.defaults import DEFAULT_HEALTH_CHECK_WEB_TIMEOUT_SECONDS
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


def check_llm_provider(ctx: BootstrapContext) -> HealthCheckResult:
    """Configuration-presence only, deliberately not a live API call — a
    real ping on every startup would burn provider quota/rate-limit budget
    for no real benefit, since llm.manager.LLMManager already falls back
    (and reports failure) the moment a real chat turn needs one."""
    providers = (
        ("Groq", ctx.settings.has_groq()),
        ("Ollama Cloud", ctx.settings.has_ollama_cloud()),
    )
    have = [name for name, ok in providers if ok]
    if not have:
        return HealthCheckResult(
            "llm_provider", "offline", "No LLM provider configured (see .env.example)"
        )
    return HealthCheckResult("llm_provider", "ok", ", ".join(have))


def check_vector_index(ctx: BootstrapContext) -> HealthCheckResult:
    """A missing index (nothing indexed yet, e.g. a fresh install) is normal,
    not a failure — only an index file that exists but fails to load is
    reported as an error. Doesn't load the embedding model (slow) since
    reading a FAISS index doesn't require it."""
    index_path = ctx.settings.indexes_dir / "vectors.faiss"
    if not index_path.exists():
        return HealthCheckResult("vector_index", "ok", "No index built yet")
    try:
        import faiss

        index = faiss.read_index(str(index_path))
        return HealthCheckResult("vector_index", "ok", f"{index.ntotal} vectors")
    except Exception as exc:  # pragma: no cover - defensive
        return HealthCheckResult("vector_index", "error", str(exc))


def check_web_search(ctx: BootstrapContext) -> HealthCheckResult:
    """The one live network call in this module — SearXNG has no
    configuration-only signal (spec.md §50's own example shows
    "SearXNG: OFFLINE" as a *reachability* state), so it needs a real
    request. Short-timeboxed so an unreachable instance can't stall
    startup."""
    url = ctx.settings.searxng_url.rstrip("/")
    try:
        resp = httpx.get(url, timeout=DEFAULT_HEALTH_CHECK_WEB_TIMEOUT_SECONDS)
        if resp.status_code >= 500:
            return HealthCheckResult("web_search", "error", f"HTTP {resp.status_code}")
        return HealthCheckResult("web_search", "ok", url)
    except httpx.HTTPError as exc:
        return HealthCheckResult("web_search", "offline", f"{url} unreachable: {exc}")


def check_voice(ctx: BootstrapContext) -> HealthCheckResult:
    if not ctx.settings.jarvis_enable_voice:
        return HealthCheckResult("voice", "ok", "Disabled (JARVIS_ENABLE_VOICE=false)")

    from voice.tts_local import resolve_voice_path

    cloud_ready = ctx.settings.has_groq() or ctx.settings.has_deepgram()
    local_tts_ready = resolve_voice_path(ctx.settings).exists()
    # Local STT (faster-whisper) needs no pre-downloaded file - it fetches
    # its model on first use - so it isn't part of this readiness check.
    if cloud_ready or local_tts_ready:
        return HealthCheckResult("voice", "ok")
    return HealthCheckResult(
        "voice",
        "offline",
        "No cloud voice provider configured and no local Piper voice found — "
        "see README's Voice section",
    )


def check_scheduler(ctx: BootstrapContext) -> HealthCheckResult:
    try:
        import apscheduler  # noqa: F401

        conn = connect(ctx.settings.db_path)
        try:
            conn.execute("SELECT 1 FROM reminders LIMIT 1").fetchall()
        finally:
            conn.close()
        return HealthCheckResult("scheduler", "ok")
    except Exception as exc:  # pragma: no cover - defensive
        return HealthCheckResult("scheduler", "error", str(exc))


def check_ui(ctx: BootstrapContext) -> HealthCheckResult:  # noqa: ARG001
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as exc:  # pragma: no cover - defensive
        return HealthCheckResult("ui", "error", str(exc))
    return HealthCheckResult("ui", "ok")


def run_health_checks(ctx: BootstrapContext) -> list[HealthCheckResult]:
    """Runs every subsystem check from spec.md §50 and logs each result.
    Never raises — a broken check reports its own "error" state instead of
    taking down startup (see each check_* function)."""
    results = [
        check_config(ctx),
        check_database(ctx),
        check_vector_index(ctx),
        check_llm_provider(ctx),
        check_web_search(ctx),
        check_voice(ctx),
        check_scheduler(ctx),
        check_ui(ctx),
    ]
    for result in results:
        logger.info("Health check: %s = %s (%s)", result.component, result.state, result.detail)
    return results


def summarize_health_warnings(results: list[HealthCheckResult]) -> str | None:
    """A short, user-facing summary of any non-"ok" component, or None if
    everything's healthy. Meant for a non-blocking UI banner (spec.md §50:
    "Display warnings without preventing unrelated functionality from
    working") — never a dialog the user must dismiss before continuing."""
    degraded = [r for r in results if r.state != "ok"]
    if not degraded:
        return None
    parts = [f"{r.component.replace('_', ' ')}: {r.state}" for r in degraded]
    return "⚠ " + "; ".join(parts)


def shutdown(ctx: BootstrapContext) -> None:
    """Graceful shutdown hook. Called on normal app exit."""
    logger.info("JARVIS shutting down.")
    log_event("shutdown", status="success")

from __future__ import annotations

import logging

import httpx
from app.bootstrap import BootstrapContext
from web.searxng_process import SearXNGProcessManager

from app import lifecycle


def _ctx(settings) -> BootstrapContext:
    return BootstrapContext(
        settings=settings,
        logger=logging.getLogger("test"),
        migrations_applied=[],
        searxng=SearXNGProcessManager(settings),
    )


# --- check_llm_provider ------------------------------------------------------


def test_llm_provider_ok_when_groq_configured(real_db, monkeypatch):
    # has_groq()/has_ollama_cloud() are plain methods, not pydantic fields -
    # pydantic v2 rejects setattr on non-field names, so patch the actual
    # field each reads instead (also more realistic: this is exactly what a
    # real .env sets).
    monkeypatch.setattr(real_db, "groq_api_key", "fake-key")
    monkeypatch.setattr(real_db, "ollama_cloud_api_key", None)
    result = lifecycle.check_llm_provider(_ctx(real_db))
    assert result.state == "ok"
    assert "Groq" in result.detail


def test_llm_provider_offline_when_none_configured(real_db, monkeypatch):
    monkeypatch.setattr(real_db, "groq_api_key", None)
    monkeypatch.setattr(real_db, "ollama_cloud_api_key", None)
    result = lifecycle.check_llm_provider(_ctx(real_db))
    assert result.state == "offline"


# --- check_vector_index ------------------------------------------------------


def test_vector_index_ok_when_no_index_built_yet(real_db):
    result = lifecycle.check_vector_index(_ctx(real_db))
    assert result.state == "ok"
    assert "No index" in result.detail


def test_vector_index_ok_when_index_loads(real_db):
    import faiss

    index_path = real_db.indexes_dir / "vectors.faiss"
    faiss.write_index(faiss.IndexFlatIP(8), str(index_path))
    result = lifecycle.check_vector_index(_ctx(real_db))
    assert result.state == "ok"


def test_vector_index_error_on_corrupt_file(real_db):
    index_path = real_db.indexes_dir / "vectors.faiss"
    index_path.write_bytes(b"not a real faiss index")
    result = lifecycle.check_vector_index(_ctx(real_db))
    assert result.state == "error"


# --- check_web_search (SearXNG) ----------------------------------------------


def test_web_search_ok_when_reachable(real_db, monkeypatch):
    def fake_get(url, timeout):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(lifecycle.httpx, "get", fake_get)
    result = lifecycle.check_web_search(_ctx(real_db))
    assert result.state == "ok"


def test_web_search_offline_when_unreachable(real_db, monkeypatch):
    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(lifecycle.httpx, "get", fake_get)
    result = lifecycle.check_web_search(_ctx(real_db))
    assert result.state == "offline"


def test_web_search_error_on_server_error(real_db, monkeypatch):
    def fake_get(url, timeout):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(lifecycle.httpx, "get", fake_get)
    result = lifecycle.check_web_search(_ctx(real_db))
    assert result.state == "error"


# --- check_voice --------------------------------------------------------------


def test_voice_ok_when_disabled(real_db, monkeypatch):
    monkeypatch.setattr(real_db, "jarvis_enable_voice", False)
    result = lifecycle.check_voice(_ctx(real_db))
    assert result.state == "ok"
    assert "Disabled" in result.detail


def test_voice_ok_when_cloud_configured(real_db, monkeypatch):
    monkeypatch.setattr(real_db, "jarvis_enable_voice", True)
    monkeypatch.setattr(real_db, "groq_api_key", "fake-key")
    monkeypatch.setattr(real_db, "deepgram_api_key", None)
    result = lifecycle.check_voice(_ctx(real_db))
    assert result.state == "ok"


def test_voice_offline_when_nothing_ready(real_db, monkeypatch):
    monkeypatch.setattr(real_db, "jarvis_enable_voice", True)
    monkeypatch.setattr(real_db, "groq_api_key", None)
    monkeypatch.setattr(real_db, "deepgram_api_key", None)
    from voice import tts_local

    monkeypatch.setattr(
        tts_local, "resolve_voice_path", lambda settings: real_db.voices_dir / "x.onnx"
    )
    result = lifecycle.check_voice(_ctx(real_db))
    assert result.state == "offline"


# --- check_scheduler / check_ui / check_database ------------------------------


def test_scheduler_ok(real_db):
    assert lifecycle.check_scheduler(_ctx(real_db)).state == "ok"


def test_ui_ok():
    result = lifecycle.check_ui(_ctx(None))
    assert result.state == "ok"


def test_database_ok(real_db):
    assert lifecycle.check_database(_ctx(real_db)).state == "ok"


# --- run_health_checks / summarize_health_warnings ----------------------------


def test_run_health_checks_returns_all_eight_components(real_db, monkeypatch):
    # Avoid a real network call in this aggregate test.
    def fake_get(url, timeout):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(lifecycle.httpx, "get", fake_get)
    results = lifecycle.run_health_checks(_ctx(real_db))
    components = {r.component for r in results}
    assert components == {
        "configuration", "database", "vector_index", "llm_provider",
        "web_search", "voice", "scheduler", "ui",
    }


def test_summarize_health_warnings_none_when_all_ok():
    from app.lifecycle import HealthCheckResult

    results = [HealthCheckResult("database", "ok"), HealthCheckResult("ui", "ok")]
    assert lifecycle.summarize_health_warnings(results) is None


def test_summarize_health_warnings_reports_partial_offline():
    from app.lifecycle import HealthCheckResult

    results = [
        HealthCheckResult("database", "ok"),
        HealthCheckResult("web_search", "offline", "unreachable"),
        HealthCheckResult("voice", "ok"),
    ]
    summary = lifecycle.summarize_health_warnings(results)
    assert summary is not None
    assert "web search" in summary
    assert "database" not in summary
    assert "voice" not in summary

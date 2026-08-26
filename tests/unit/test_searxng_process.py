from __future__ import annotations

import subprocess
from types import SimpleNamespace

import httpx
import pytest
from config.settings import Settings
from web.searxng_process import SearXNGProcessManager


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _venv_python(tmp_path):
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("")
    return python


# --- _python_exe --------------------------------------------------------------


def test_python_exe_none_without_searxng_dir():
    mgr = SearXNGProcessManager(_settings())
    assert mgr._python_exe() is None


def test_python_exe_none_when_venv_missing(tmp_path):
    mgr = SearXNGProcessManager(_settings(SEARXNG_DIR=str(tmp_path)))
    assert mgr._python_exe() is None


def test_python_exe_found_when_venv_exists(tmp_path):
    python = _venv_python(tmp_path)
    mgr = SearXNGProcessManager(_settings(SEARXNG_DIR=str(tmp_path)))
    assert mgr._python_exe() == python


# --- start(): disabled / already-reachable / missing-venv gates -----------


def test_start_noop_when_autostart_disabled(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("Popen should not be called")

    monkeypatch.setattr(subprocess, "Popen", fail)
    mgr = SearXNGProcessManager(_settings(SEARXNG_AUTOSTART=False))
    mgr.start()
    assert mgr._process is None


def test_start_skips_when_already_reachable(monkeypatch, tmp_path):
    _venv_python(tmp_path)

    def fake_get(url, timeout):
        return httpx.Response(200, request=httpx.Request("GET", url))

    def fail_popen(*a, **kw):
        raise AssertionError("Popen should not be called when already reachable")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fail_popen)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()
    assert mgr._process is None


def test_start_skips_when_no_venv_found(monkeypatch, tmp_path):
    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    def fail_popen(*a, **kw):
        raise AssertionError("Popen should not be called without a venv")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fail_popen)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()
    assert mgr._process is None


# --- start(): actually spawning ------------------------------------------------


def test_start_spawns_subprocess_with_correct_args(monkeypatch, tmp_path):
    python = _venv_python(tmp_path)

    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    calls = []

    def fake_popen(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(pid=1234, poll=lambda: None)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()

    assert len(calls) == 1
    args, kw = calls[0]
    assert args == [str(python), "-m", "searx.webapp"]
    assert kw["cwd"] == str(tmp_path)
    assert mgr.is_running is True


def test_start_does_not_double_spawn_when_already_running(monkeypatch, tmp_path):
    _venv_python(tmp_path)

    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    calls = []

    def fake_popen(args, **kw):
        calls.append(args)
        return SimpleNamespace(pid=1234, poll=lambda: None)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()
    mgr.start()
    assert len(calls) == 1


def test_start_handles_popen_oserror_gracefully(monkeypatch, tmp_path):
    _venv_python(tmp_path)

    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    def raise_oserror(*a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", raise_oserror)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()  # must not raise
    assert mgr._process is None


# --- stop() ---------------------------------------------------------------


def test_stop_is_noop_when_never_started():
    mgr = SearXNGProcessManager(_settings())
    mgr.stop()  # must not raise


def test_stop_terminates_running_process():
    terminated = []
    waited = []
    proc = SimpleNamespace(
        pid=1234,
        poll=lambda: None,
        terminate=lambda: terminated.append(True),
        wait=lambda timeout: waited.append(timeout),
    )
    mgr = SearXNGProcessManager(_settings())
    mgr._process = proc

    mgr.stop()

    assert terminated == [True]
    assert waited == [5]
    assert mgr._process is None
    assert mgr.is_running is False


def test_stop_kills_on_timeout():
    killed = []

    def raise_timeout(timeout):
        raise subprocess.TimeoutExpired(cmd="searx", timeout=timeout)

    proc = SimpleNamespace(
        pid=1234,
        poll=lambda: None,
        terminate=lambda: None,
        wait=raise_timeout,
        kill=lambda: killed.append(True),
    )
    mgr = SearXNGProcessManager(_settings())
    mgr._process = proc

    mgr.stop()

    assert killed == [True]
    assert mgr._process is None


def test_stop_never_touches_a_process_it_did_not_spawn(monkeypatch, tmp_path):
    """If start() skipped spawning because SearXNG was already reachable,
    _process stays None — stop() must never accidentally kill someone
    else's instance."""
    _venv_python(tmp_path)

    def fake_get(url, timeout):
        return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    mgr = SearXNGProcessManager(
        _settings(SEARXNG_AUTOSTART=True, SEARXNG_DIR=str(tmp_path))
    )
    mgr.start()
    assert mgr._process is None
    mgr.stop()  # must not raise, nothing to stop
    assert mgr._process is None


# --- is_running -------------------------------------------------------------


def test_is_running_false_when_process_exited():
    proc = SimpleNamespace(pid=1234, poll=lambda: 1)  # non-None = exited
    mgr = SearXNGProcessManager(_settings())
    mgr._process = proc
    assert mgr.is_running is False


@pytest.mark.parametrize("autostart", [True, False])
def test_is_running_false_before_start(autostart):
    mgr = SearXNGProcessManager(_settings(SEARXNG_AUTOSTART=autostart))
    assert mgr.is_running is False

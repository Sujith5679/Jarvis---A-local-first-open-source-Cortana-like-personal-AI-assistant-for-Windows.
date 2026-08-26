from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app import windows_startup


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_startup_enabled_true_when_query_succeeds(monkeypatch):
    monkeypatch.setattr(
        windows_startup.subprocess, "run", lambda *a, **kw: _completed(0)
    )
    assert windows_startup.is_startup_enabled() is True


def test_is_startup_enabled_false_when_query_fails(monkeypatch):
    monkeypatch.setattr(
        windows_startup.subprocess, "run", lambda *a, **kw: _completed(1, stderr="not found")
    )
    assert windows_startup.is_startup_enabled() is False


def test_enable_startup_raises_if_launcher_missing(monkeypatch):
    monkeypatch.setattr(windows_startup, "_LAUNCHER", windows_startup.BASE_DIR / "nope.bat")
    with pytest.raises(windows_startup.StartupTaskError, match="Launcher not found"):
        windows_startup.enable_startup()


def test_enable_startup_calls_schtasks_create(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(windows_startup, "_LAUNCHER", launcher)

    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(windows_startup.subprocess, "run", fake_run)
    windows_startup.enable_startup()

    assert calls
    args = calls[0]
    assert "/Create" in args
    assert windows_startup.TASK_NAME in args
    assert any(str(launcher) in a for a in args)


def test_enable_startup_raises_on_schtasks_failure(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(windows_startup, "_LAUNCHER", launcher)
    monkeypatch.setattr(
        windows_startup.subprocess,
        "run",
        lambda *a, **kw: _completed(1, stderr="Access is denied"),
    )
    with pytest.raises(windows_startup.StartupTaskError, match="Access is denied"):
        windows_startup.enable_startup()


def test_disable_startup_calls_schtasks_delete(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(windows_startup.subprocess, "run", fake_run)
    windows_startup.disable_startup()

    assert "/Delete" in calls[0]
    assert windows_startup.TASK_NAME in calls[0]


def test_disable_startup_is_a_noop_when_task_absent(monkeypatch):
    monkeypatch.setattr(
        windows_startup.subprocess,
        "run",
        lambda *a, **kw: _completed(1, stderr="ERROR: The system cannot find the file specified."),
    )
    windows_startup.disable_startup()  # must not raise


def test_disable_startup_raises_on_other_failure(monkeypatch):
    monkeypatch.setattr(
        windows_startup.subprocess,
        "run",
        lambda *a, **kw: _completed(1, stderr="Access is denied"),
    )
    with pytest.raises(windows_startup.StartupTaskError):
        windows_startup.disable_startup()


def test_query_timeout_propagates(monkeypatch):
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="schtasks", timeout=10)

    monkeypatch.setattr(windows_startup.subprocess, "run", raise_timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        windows_startup.is_startup_enabled()

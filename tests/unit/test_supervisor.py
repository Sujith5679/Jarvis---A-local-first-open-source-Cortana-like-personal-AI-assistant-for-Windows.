from __future__ import annotations

import subprocess

from app import supervisor


def test_find_main_window_returns_hwnd(monkeypatch):
    monkeypatch.setattr(
        supervisor.ctypes.windll.user32, "FindWindowW", lambda cls, title: 4242, raising=False
    )
    assert supervisor.find_main_window() == 4242


def test_find_main_window_zero_when_not_running(monkeypatch):
    monkeypatch.setattr(
        supervisor.ctypes.windll.user32, "FindWindowW", lambda cls, title: 0, raising=False
    )
    assert supervisor.find_main_window() == 0


def test_bring_to_foreground_calls_show_and_set_foreground(monkeypatch):
    calls = []
    monkeypatch.setattr(
        supervisor.ctypes.windll.user32,
        "ShowWindow",
        lambda hwnd, cmd: calls.append(("show", hwnd, cmd)),
        raising=False,
    )
    monkeypatch.setattr(
        supervisor.ctypes.windll.user32,
        "SetForegroundWindow",
        lambda hwnd: calls.append(("foreground", hwnd)),
        raising=False,
    )

    supervisor.bring_to_foreground(4242)

    assert calls == [("show", 4242, supervisor.SW_RESTORE), ("foreground", 4242)]


def test_open_or_focus_brings_existing_window_forward_without_launching(monkeypatch):
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 4242)
    foregrounded = []
    monkeypatch.setattr(supervisor, "bring_to_foreground", lambda hwnd: foregrounded.append(hwnd))

    def fail(*a, **kw):
        raise AssertionError("Popen should not be called when the window already exists")

    monkeypatch.setattr(subprocess, "Popen", fail)

    supervisor.Supervisor().open_or_focus()
    assert foregrounded == [4242]


def test_open_or_focus_launches_when_not_running(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(supervisor, "LAUNCHER", launcher)
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 0)

    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))

    supervisor.Supervisor().open_or_focus()

    assert len(calls) == 1
    args, kw = calls[0]
    assert args == ["cmd", "/c", str(launcher)]


def test_open_or_focus_warns_without_raising_when_launcher_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "LAUNCHER", tmp_path / "nope.bat")
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 0)

    def fail(*a, **kw):
        raise AssertionError("Popen should not be called when the launcher is missing")

    monkeypatch.setattr(subprocess, "Popen", fail)

    supervisor.Supervisor().open_or_focus()  # must not raise


def test_open_or_focus_handles_popen_oserror_gracefully(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(supervisor, "LAUNCHER", launcher)
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 0)

    def raise_oserror(*a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(subprocess, "Popen", raise_oserror)

    sup = supervisor.Supervisor()
    sup.open_or_focus()  # must not raise
    assert sup._last_launch is None  # a failed launch doesn't start the debounce window


def test_open_or_focus_debounces_repeated_triggers_while_still_starting(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(supervisor, "LAUNCHER", launcher)
    # Never becomes ready in this test - only the debounce is under test.
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 0)

    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))

    clock = {"t": 0.0}
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock["t"])

    sup = supervisor.Supervisor()
    sup.open_or_focus()
    assert len(calls) == 1

    clock["t"] += 1.0  # well within RELAUNCH_DEBOUNCE_SECONDS
    sup.open_or_focus()
    assert len(calls) == 1  # suppressed - still "starting up"


def test_open_or_focus_relaunches_after_debounce_expires(monkeypatch, tmp_path):
    launcher = tmp_path / "start_jarvis.bat"
    launcher.write_text("@echo off")
    monkeypatch.setattr(supervisor, "LAUNCHER", launcher)
    monkeypatch.setattr(supervisor, "find_main_window", lambda: 0)

    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))

    clock = {"t": 0.0}
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock["t"])

    sup = supervisor.Supervisor()
    sup.open_or_focus()
    assert len(calls) == 1

    clock["t"] += supervisor.RELAUNCH_DEBOUNCE_SECONDS + 1
    sup.open_or_focus()
    assert len(calls) == 2

from __future__ import annotations

import pytest
from tools import windows

# --- launch_application: allowlist-only, never a raw command string -------


@pytest.mark.asyncio
async def test_launch_known_app_succeeds(monkeypatch):
    calls = []
    monkeypatch.setattr(windows.subprocess, "Popen", lambda args: calls.append(args))

    result = await windows.launch_application_handler("notepad")
    assert result == {"application": "notepad", "executable": "notepad.exe", "launched": True}
    assert calls == [["notepad.exe"]]


@pytest.mark.asyncio
async def test_launch_is_case_and_whitespace_insensitive(monkeypatch):
    calls = []
    monkeypatch.setattr(windows.subprocess, "Popen", lambda args: calls.append(args))

    result = await windows.launch_application_handler("  Notepad  ")
    assert result["launched"] is True
    assert calls == [["notepad.exe"]]


@pytest.mark.asyncio
async def test_launch_unknown_app_rejected_without_calling_popen(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("Popen should never be called for an unallowlisted app")

    monkeypatch.setattr(windows.subprocess, "Popen", fail)

    result = await windows.launch_application_handler("powershell")
    assert "error" in result
    assert "not in the allowed application list" in result["error"]


@pytest.mark.asyncio
async def test_launch_rejects_shell_metacharacters_as_unknown(monkeypatch):
    """A key like 'notepad.exe & calc.exe' must not partially match — the
    allowlist is an exact-match dict, not a substring/prefix check."""

    def fail(*a, **kw):
        raise AssertionError("Popen should never be called")

    monkeypatch.setattr(windows.subprocess, "Popen", fail)

    result = await windows.launch_application_handler("notepad.exe & calc.exe")
    assert "error" in result


@pytest.mark.asyncio
async def test_launch_popen_failure_returns_error_not_exception(monkeypatch):
    def raise_oserror(args):
        raise OSError("not found")

    monkeypatch.setattr(windows.subprocess, "Popen", raise_oserror)

    result = await windows.launch_application_handler("notepad")
    assert "error" in result


# --- open_file: reuses the exact indexed-folder allowlist check -----------


@pytest.mark.asyncio
async def test_open_file_outside_indexed_folders_rejected(monkeypatch):
    monkeypatch.setattr(windows.folders_repo, "is_path_within_indexed_folders", lambda p: False)

    def fail(path):
        raise AssertionError("startfile should never be called")

    monkeypatch.setattr(windows.os, "startfile", fail)

    result = await windows.open_file_handler(r"C:\Windows\System32\cmd.exe")
    assert "error" in result
    assert "allowed indexed folders" in result["error"]


@pytest.mark.asyncio
async def test_open_file_missing_file_rejected(monkeypatch, tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    monkeypatch.setattr(windows.folders_repo, "is_path_within_indexed_folders", lambda p: True)

    result = await windows.open_file_handler(str(missing))
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_open_file_succeeds(monkeypatch, tmp_path):
    target = tmp_path / "report.txt"
    target.write_text("hello")
    monkeypatch.setattr(windows.folders_repo, "is_path_within_indexed_folders", lambda p: True)

    calls = []
    monkeypatch.setattr(windows.os, "startfile", lambda p: calls.append(p))

    result = await windows.open_file_handler(str(target))
    assert result == {"path": str(target), "opened": True}
    assert calls == [str(target)]


# --- lock_system: no arguments, no allowlist needed ------------------------


@pytest.mark.asyncio
async def test_lock_system_succeeds(monkeypatch):
    monkeypatch.setattr(windows.ctypes.windll.user32, "LockWorkStation", lambda: 1, raising=False)

    result = await windows.lock_system_handler()
    assert result == {"locked": True}


@pytest.mark.asyncio
async def test_lock_system_reports_windows_failure(monkeypatch):
    monkeypatch.setattr(windows.ctypes.windll.user32, "LockWorkStation", lambda: 0, raising=False)

    result = await windows.lock_system_handler()
    assert "error" in result


# --- Tool metadata: all three require confirmation (spec.md §2.3) ---------


def test_all_windows_tools_require_confirmation():
    for tool in (windows.LAUNCH_APPLICATION, windows.OPEN_FILE, windows.LOCK_SYSTEM):
        assert tool.metadata.requires_confirmation is True


def test_register_adds_all_three_tools():
    from tools.registry import ToolRegistry

    registry = ToolRegistry()
    windows.register(registry)
    names = {t.name for t in registry.all()}
    assert names == {"launch_application", "open_file", "lock_system"}

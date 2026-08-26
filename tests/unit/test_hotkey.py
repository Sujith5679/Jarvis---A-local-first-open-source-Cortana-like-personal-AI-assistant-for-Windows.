from __future__ import annotations

import sys
import types

from ui.hotkey import GlobalHotkey


def _install_fake_keyboard_module(monkeypatch, *, add_hotkey=None, remove_hotkey=None):
    """`keyboard` does a real system-wide hook on import in some environments,
    so tests fake the module out at the sys.modules level rather than trying
    to monkeypatch attributes of the real thing."""
    fake = types.SimpleNamespace(
        add_hotkey=add_hotkey or (lambda combo, cb: f"handle:{combo}"),
        remove_hotkey=remove_hotkey or (lambda handle: None),
    )
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    return fake


def test_register_success_returns_true_and_stores_handle(monkeypatch):
    calls = []

    def fake_add_hotkey(combo, cb):
        calls.append((combo, cb))
        return "the-handle"

    _install_fake_keyboard_module(monkeypatch, add_hotkey=fake_add_hotkey)

    hk = GlobalHotkey("ctrl+space")
    assert hk.register() is True
    assert hk._handle == "the-handle"
    assert calls[0][0] == "ctrl+space"
    assert calls[0][1] == hk.bridge.triggered.emit


def test_register_failure_degrades_gracefully(monkeypatch):
    def raise_error(combo, cb):
        raise RuntimeError("hook install failed")

    _install_fake_keyboard_module(monkeypatch, add_hotkey=raise_error)

    hk = GlobalHotkey("ctrl+space")
    assert hk.register() is False
    assert hk._handle is None


def test_register_import_error_degrades_gracefully(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyboard", None)  # forces ImportError on `import keyboard`

    hk = GlobalHotkey("ctrl+space")
    assert hk.register() is False


def test_unregister_calls_remove_hotkey(monkeypatch):
    calls = []
    _install_fake_keyboard_module(monkeypatch, remove_hotkey=lambda h: calls.append(h))

    hk = GlobalHotkey("ctrl+space")
    hk._handle = "the-handle"
    hk.unregister()

    assert calls == ["the-handle"]
    assert hk._handle is None


def test_unregister_without_prior_register_is_a_noop(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("remove_hotkey should not be called")

    _install_fake_keyboard_module(monkeypatch, remove_hotkey=fail)

    hk = GlobalHotkey("ctrl+space")
    hk.unregister()  # must not raise, must not call remove_hotkey


def test_unregister_swallows_errors(monkeypatch):
    def raise_error(handle):
        raise RuntimeError("already gone")

    _install_fake_keyboard_module(monkeypatch, remove_hotkey=raise_error)

    hk = GlobalHotkey("ctrl+space")
    hk._handle = "the-handle"
    hk.unregister()  # must not raise
    assert hk._handle is None


def test_triggered_signal_fires_registered_callback():
    """The bridge is a real QObject signal — connecting a plain callback and
    emitting it directly (bypassing the fake keyboard lib entirely) proves
    the wiring works without needing a real global hook."""
    hk = GlobalHotkey("ctrl+space")
    fired = []
    hk.bridge.triggered.connect(lambda: fired.append(True))
    hk.bridge.triggered.emit()
    assert fired == [True]

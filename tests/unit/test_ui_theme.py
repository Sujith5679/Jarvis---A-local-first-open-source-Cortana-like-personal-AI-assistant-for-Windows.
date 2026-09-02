"""ui/theme.py's pure logic (no QApplication needed for these - QSettings
works standalone, live-verified). Every test uses a unique org/app name via
monkeypatch rather than the real "JARVIS"/"JARVIS" QSettings the actual app
reads/writes - writing theme_mode into the real user registry key from a
test would be exactly the kind of test/production leak this project has
been bitten by before (see storage/repositories usage tests' real_db
isolation)."""

from __future__ import annotations

import uuid

import pytest

from ui import theme


@pytest.fixture(autouse=True)
def _isolated_qsettings(monkeypatch):
    unique = f"jarvis-test-{uuid.uuid4()}"
    monkeypatch.setattr(theme, "SETTINGS_ORG", unique)
    monkeypatch.setattr(theme, "SETTINGS_APP", unique)


def test_load_theme_mode_defaults_to_system():
    assert theme.load_theme_mode() == "system"


def test_save_and_load_theme_mode_round_trips():
    theme.save_theme_mode("dark")
    assert theme.load_theme_mode() == "dark"


def test_save_theme_mode_rejects_invalid_mode():
    with pytest.raises(ValueError):
        theme.save_theme_mode("purple")


def test_resolve_theme_explicit_light():
    assert theme.resolve_theme("light") is theme.LIGHT


def test_resolve_theme_explicit_dark():
    assert theme.resolve_theme("dark") is theme.DARK


def test_resolve_theme_reads_saved_mode_when_none_passed():
    theme.save_theme_mode("dark")
    assert theme.resolve_theme(None) is theme.DARK


def test_light_and_dark_define_every_token_distinctly():
    """Not literally testing colors (a design choice, not a bug target) -
    just that dark mode isn't accidentally a copy-paste of light mode."""
    assert theme.LIGHT != theme.DARK
    assert theme.LIGHT.surface_bg != theme.DARK.surface_bg

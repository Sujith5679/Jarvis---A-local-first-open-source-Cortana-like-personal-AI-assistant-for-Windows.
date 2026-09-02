"""Light/dark theme tokens for the chat UI (ui/messages.py, ui/chat_window.py).

Kept as one small module rather than scattering hex colors across widgets so
switching themes means updating one dict, not hunting through stylesheets -
same "no hard-coded values behind a call site" spirit as config/defaults.py,
just for UI tokens instead of behavioral tunables.

Persisted as a plain QSettings value (not a DB row/config.defaults constant)
- this is a per-machine display preference a user flips from the chat
window's menu, not application data anyone would want backed up or synced
with conversations/notes/tasks the way config/settings.py's .env-backed
Settings are.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

SETTINGS_ORG = "JARVIS"
SETTINGS_APP = "JARVIS"  # shared QSettings namespace - ui/chat_window.py also
# stores window geometry here (_GEOMETRY_SETTINGS_KEY), one registry key
# space for all per-machine UI preferences rather than a scope per widget.
_THEME_MODE_KEY = "ui/theme_mode"
VALID_THEME_MODES = ("light", "dark", "system")
DEFAULT_THEME_MODE = "system"


@dataclass(frozen=True)
class Theme:
    name: str
    window_bg: str
    surface_bg: str  # chat log background
    text: str
    muted_text: str
    border: str
    input_bg: str
    accent: str  # send button / links
    user_bubble_bg: str
    user_bubble_text: str
    assistant_bubble_bg: str
    assistant_bubble_text: str
    error_text: str
    status_text: str


LIGHT = Theme(
    name="light",
    window_bg="#f9fafb",
    surface_bg="#ffffff",
    text="#111827",
    muted_text="#6b7280",
    border="#e5e7eb",
    input_bg="#ffffff",
    accent="#2563eb",
    user_bubble_bg="#2563eb",
    user_bubble_text="#ffffff",
    assistant_bubble_bg="#f3f4f6",
    assistant_bubble_text="#111827",
    error_text="#dc2626",
    status_text="#9ca3af",
)

DARK = Theme(
    name="dark",
    window_bg="#1f2937",
    surface_bg="#111827",
    text="#f3f4f6",
    muted_text="#9ca3af",
    border="#374151",
    input_bg="#1f2937",
    accent="#3b82f6",
    user_bubble_bg="#2563eb",
    user_bubble_text="#ffffff",
    assistant_bubble_bg="#374151",
    assistant_bubble_text="#f3f4f6",
    error_text="#f87171",
    status_text="#6b7280",
)


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_theme_mode() -> str:
    mode = _settings().value(_THEME_MODE_KEY, DEFAULT_THEME_MODE)
    return mode if mode in VALID_THEME_MODES else DEFAULT_THEME_MODE


def save_theme_mode(mode: str) -> None:
    if mode not in VALID_THEME_MODES:
        raise ValueError(f"Invalid theme mode: {mode!r}. Must be one of {VALID_THEME_MODES}.")
    _settings().setValue(_THEME_MODE_KEY, mode)


def _detect_system_theme() -> Theme:
    """Best-effort OS dark-mode detection via Qt 6.5+'s
    styleHints().colorScheme(). Falls back to LIGHT if Qt can't tell (e.g.
    platform doesn't report it, live-verified to return Unknown under the
    offscreen test platform) - never crashes, never guesses dark when we
    genuinely don't know."""
    try:
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme.name == "Dark":
            return DARK
        return LIGHT
    except Exception:
        return LIGHT


def resolve_theme(mode: str | None = None) -> Theme:
    """`mode=None` reads the saved preference (load_theme_mode())."""
    mode = mode or load_theme_mode()
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    return _detect_system_theme()

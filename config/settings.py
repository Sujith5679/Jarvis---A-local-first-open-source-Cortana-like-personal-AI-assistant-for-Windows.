"""Typed, `.env`-driven application configuration.

All credentials and personal configuration must come from `.env` and/or local
config (spec.md §10). Nothing here should ever be hardcoded with a real secret.
Use `get_settings()` everywhere instead of instantiating `Settings()` directly
so the whole process shares one cached, validated configuration object.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.defaults import DEFAULT_HOTKEY

# Repository root = parent of the `config/` package directory.
BASE_DIR = Path(__file__).resolve().parent.parent


class ConfigurationMode(StrEnum):
    """spec.md §34 — provider/behavior policy presets."""

    FAST = "fast"          # Groq primary, Ollama Cloud fallback
    PRIVACY = "privacy"    # local model preferred, no cloud context
    OFFLINE = "offline"    # local-only, no external calls
    AUTO = "auto"          # use configured provider policy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM providers ---
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str | None = Field(default=None, alias="GROQ_MODEL")

    ollama_cloud_api_key: str | None = Field(default=None, alias="OLLAMA_CLOUD_API_KEY")
    ollama_cloud_model: str | None = Field(default=None, alias="OLLAMA_CLOUD_MODEL")

    ollama_local_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_LOCAL_BASE_URL"
    )
    ollama_local_model: str | None = Field(default=None, alias="OLLAMA_LOCAL_MODEL")

    # --- Web ---
    searxng_url: str = Field(default="http://localhost:8080", alias="SEARXNG_URL")
    # Optional: let JARVIS manage its own local SearXNG process (see
    # web/searxng_process.py) rather than requiring it to be started
    # separately every time (README's "Web search" section). Off by default
    # since it assumes SearXNG is checked out at searxng_dir with its own
    # venv, exactly as the README's manual setup instructions produce -
    # never assumed present.
    searxng_autostart: bool = Field(default=False, alias="SEARXNG_AUTOSTART")
    searxng_dir: str | None = Field(default=None, alias="SEARXNG_DIR")

    # --- User ---
    jarvis_user_name: str | None = Field(default=None, alias="JARVIS_USER_NAME")
    jarvis_user_email: str | None = Field(default=None, alias="JARVIS_USER_EMAIL")
    jarvis_timezone: str = Field(default="Asia/Kolkata", alias="JARVIS_TIMEZONE")

    # --- Application ---
    jarvis_log_level: str = Field(default="INFO", alias="JARVIS_LOG_LEVEL")
    jarvis_data_dir: str | None = Field(default=None, alias="JARVIS_DATA_DIR")
    # spec.md §27: "Do not force automatic startup" - defaults OFF. This
    # field only seeds the "Start JARVIS with Windows" checkbox's initial
    # display value the very first time Settings opens; ui/settings.py
    # otherwise reads the real Task Scheduler state directly
    # (app/windows_startup.py's is_startup_enabled()), and only
    # enable_startup()/disable_startup() (an explicit checkbox toggle) ever
    # changes it - nothing reads this field automatically at bootstrap.
    jarvis_start_on_boot: bool = Field(default=False, alias="JARVIS_START_ON_BOOT")
    # Currently unused/vestigial: the on-demand supervisor model
    # (app/supervisor.py) means the main app only ever launches because
    # something (a person, or the hotkey) just asked for it, so there's no
    # "start hidden" case to apply this to anymore. Left defined rather
    # than removed so an existing .env setting doesn't start erroring.
    jarvis_start_minimized: bool = Field(default=True, alias="JARVIS_START_MINIMIZED")
    jarvis_enable_voice: bool = Field(default=True, alias="JARVIS_ENABLE_VOICE")
    jarvis_enable_wake_word: bool = Field(default=False, alias="JARVIS_ENABLE_WAKE_WORD")
    # spec.md §26: configurable, defaults to Ctrl+Space. Parsed by
    # ui/hotkey.py (used by app/supervisor.py) using the `keyboard`
    # library's hotkey syntax (e.g. "ctrl+space", "ctrl+alt+j").
    jarvis_hotkey: str = Field(default=DEFAULT_HOTKEY, alias="JARVIS_HOTKEY")

    # --- Voice ---
    # Ordered, comma-separated provider chain — same idea as LLMManager's
    # Groq-then-Ollama-Cloud chain. Each is tried in order; "local" is always
    # attempted as a final safety net even if omitted or every listed
    # provider fails, so voice never simply stops working. See voice/stt.py,
    # voice/tts.py for the actual dispatch logic.
    stt_providers_raw: str = Field(default="groq,deepgram,local", alias="JARVIS_STT_PROVIDERS")
    tts_providers_raw: str = Field(default="groq,deepgram,local", alias="JARVIS_TTS_PROVIDERS")
    # Deepgram is a separate service from Groq/Ollama — its own key.
    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    # Optional override; defaults to data_dir/voices/<DEFAULT_PIPER_VOICE_NAME>.onnx
    # (see voice/tts_local.py) so a fresh install works without setting anything here.
    piper_voice_path: str | None = Field(default=None, alias="JARVIS_PIPER_VOICE_PATH")

    # --- Future Google integration ---
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str | None = Field(default=None, alias="GOOGLE_REDIRECT_URI")

    # --- Derived / not read from env directly ---
    configuration_mode: ConfigurationMode = ConfigurationMode.AUTO

    @property
    def data_dir(self) -> Path:
        path = Path(self.jarvis_data_dir) if self.jarvis_data_dir else BASE_DIR / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jarvis.db"

    @property
    def logs_dir(self) -> Path:
        path = self.data_dir / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def indexes_dir(self) -> Path:
        path = self.data_dir / "indexes"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cache_dir(self) -> Path:
        path = self.data_dir / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def voices_dir(self) -> Path:
        path = self.data_dir / "voices"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    def has_ollama_cloud(self) -> bool:
        return bool(self.ollama_cloud_api_key)

    def has_deepgram(self) -> bool:
        return bool(self.deepgram_api_key)

    @property
    def stt_providers(self) -> list[str]:
        return [p.strip() for p in self.stt_providers_raw.split(",") if p.strip()]

    @property
    def tts_providers(self) -> list[str]:
        return [p.strip() for p in self.tts_providers_raw.split(",") if p.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Tests that need a fresh instance should call `get_settings.cache_clear()`
    first (e.g. after monkeypatching environment variables).
    """
    return Settings()

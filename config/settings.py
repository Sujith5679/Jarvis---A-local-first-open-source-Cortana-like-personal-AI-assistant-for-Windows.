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

    # --- User ---
    jarvis_user_name: str | None = Field(default=None, alias="JARVIS_USER_NAME")
    jarvis_user_email: str | None = Field(default=None, alias="JARVIS_USER_EMAIL")
    jarvis_timezone: str = Field(default="Asia/Kolkata", alias="JARVIS_TIMEZONE")

    # --- Application ---
    jarvis_log_level: str = Field(default="INFO", alias="JARVIS_LOG_LEVEL")
    jarvis_data_dir: str | None = Field(default=None, alias="JARVIS_DATA_DIR")
    jarvis_start_on_boot: bool = Field(default=True, alias="JARVIS_START_ON_BOOT")
    jarvis_start_minimized: bool = Field(default=True, alias="JARVIS_START_MINIMIZED")
    jarvis_enable_voice: bool = Field(default=True, alias="JARVIS_ENABLE_VOICE")
    jarvis_enable_wake_word: bool = Field(default=False, alias="JARVIS_ENABLE_WAKE_WORD")

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

    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    def has_ollama_cloud(self) -> bool:
        return bool(self.ollama_cloud_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Tests that need a fresh instance should call `get_settings.cache_clear()`
    first (e.g. after monkeypatching environment variables).
    """
    return Settings()

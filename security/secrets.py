"""Secret handling helpers.

Rules (spec.md §10, §35):
- Secrets only ever come from environment variables / `.env`.
- Secrets are never written to SQLite, never logged, never sent to an LLM prompt.
- Any place that must show a secret-shaped value (errors, UI, audit log) must
  go through `mask()` first.

This module does not read `.env` itself — that's `config.settings.Settings`.
It only provides safe-handling utilities used wherever a secret value might
otherwise leak.
"""

from __future__ import annotations

_VISIBLE_PREFIX = 4
_VISIBLE_SUFFIX = 2


def mask(value: str | None) -> str:
    """Mask a secret for safe display in logs/errors/UI/audit entries.

    Examples:
        mask("gsk_abcdef123456") -> "gsk_...56"
        mask(None) -> "<unset>"
        mask("")   -> "<empty>"
    """
    if value is None:
        return "<unset>"
    if value == "":
        return "<empty>"
    if len(value) <= _VISIBLE_PREFIX + _VISIBLE_SUFFIX:
        return "*" * len(value)
    return f"{value[:_VISIBLE_PREFIX]}...{value[-_VISIBLE_SUFFIX:]}"


def scrub_secrets(text: str, secrets: list[str | None]) -> str:
    """Replace any occurrence of known secret values in `text` with a masked form.

    Use before writing free-form text (exception messages, provider error
    bodies, audit `result_summary`) to logs, the UI, or an audit record.
    """
    scrubbed = text
    for secret in secrets:
        if secret:
            scrubbed = scrubbed.replace(secret, mask(secret))
    return scrubbed


def known_secrets_from_settings() -> list[str | None]:
    """Convenience accessor for every secret-shaped setting, for use with scrub_secrets()."""
    from config.settings import get_settings

    s = get_settings()
    return [
        s.groq_api_key,
        s.ollama_cloud_api_key,
        s.google_client_secret,
    ]

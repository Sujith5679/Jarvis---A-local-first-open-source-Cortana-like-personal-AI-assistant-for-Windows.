"""LLM provider abstraction (spec.md §11).

Every provider (Groq, Ollama Cloud, future local Ollama, future others)
implements the same `LLMProvider` protocol so `llm.manager.LLMManager` can
treat them interchangeably and fall back between them. Provider selection is
configuration-driven — nothing in `agent/` should import a concrete provider
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    finish_reason: str | None = None
    tool_calls: list[dict] | None = None
    raw: dict | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Matches spec.md §11's provider interface."""

    name: str

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse: ...


# --- Errors -----------------------------------------------------------------
#
# Fallback should happen for connection failures, timeouts, rate limits, and
# temporary provider errors (spec.md §11). All of the below are treated as
# fallback-eligible by LLMManager for a plain chat turn, since re-issuing a
# read-only "generate a reply" request has no external side effects. Tools
# with side effects (Phase 2+) must NOT be blindly retried across providers —
# that's a separate concern enforced in the agent/tool layer, not here.


class ProviderError(Exception):
    """Base class for all provider failures."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderConnectionError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    """`retry_after`, when known, is how many seconds the provider says to
    wait before its rate-limit window resets — read from the response
    (standard `Retry-After` header, or a provider-specific equivalent),
    never guessed. `None` means the provider gave no timing signal."""

    def __init__(
        self, message: str, *, provider: str, retry_after: float | None = None
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after = retry_after


def parse_retry_after_header(value: str | None) -> float | None:
    """Parses the standard HTTP `Retry-After` header: either an integer
    number of seconds, or an HTTP-date (RFC 7231 §7.1.3). Returns None if
    absent or unparseable — callers should fall back to their own default
    backoff in that case, never assume a value."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max((dt - datetime.now(UTC)).total_seconds(), 0.0)


class ProviderAuthError(ProviderError):
    """Invalid/missing API key. Fallback-eligible so a misconfigured primary
    provider doesn't take the whole assistant down."""

    pass


class ProviderResponseError(ProviderError):
    """Provider returned a malformed/unexpected response."""

    pass


@dataclass
class AllProvidersFailedError(Exception):
    """Raised by LLMManager when every configured provider failed."""

    attempts: list[ProviderError] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.attempts:
            return (
                "No LLM provider is configured. Set GROQ_API_KEY or "
                "OLLAMA_CLOUD_API_KEY in .env."
            )
        details = "; ".join(f"{e.provider}: {e}" for e in self.attempts)
        return f"All LLM providers failed: {details}"

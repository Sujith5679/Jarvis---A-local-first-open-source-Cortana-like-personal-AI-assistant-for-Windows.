"""LLM provider abstraction (spec.md §11).

Every provider (Groq, Ollama Cloud, future local Ollama, future others)
implements the same `LLMProvider` protocol so `llm.manager.LLMManager` can
treat them interchangeably and fall back between them. Provider selection is
configuration-driven — nothing in `agent/` should import a concrete provider
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    pass


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
            return "No LLM provider is configured. Set GROQ_API_KEY or OLLAMA_CLOUD_API_KEY in .env."
        details = "; ".join(f"{e.provider}: {e}" for e in self.attempts)
        return f"All LLM providers failed: {details}"

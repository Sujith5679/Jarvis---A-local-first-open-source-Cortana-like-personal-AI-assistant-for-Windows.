"""Groq provider — primary LLM (spec.md §11).

Groq exposes an OpenAI-compatible Chat Completions API:
https://console.groq.com/docs/api-reference#chat-create
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from config.defaults import (
    DEFAULT_LLM_MAX_RETRIES,
    DEFAULT_LLM_RATE_LIMIT_MAX_WAIT_SECONDS,
    DEFAULT_LLM_RETRY_BACKOFF_SECONDS,
    DEFAULT_LLM_TIMEOUT_SECONDS,
)

from llm.base import (
    LLMResponse,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    TokenUsage,
    parse_retry_after_header,
)

logger = logging.getLogger("jarvis.llm.groq")

GROQ_API_BASE = "https://api.groq.com/openai/v1"
# gpt-oss-120b: large context (131k), strong tool-calling support (OpenAI harmony
# format), and available on Ollama Cloud too so provider fallback doesn't change
# model family. Verified against the live /v1/models catalog — re-check
# periodically as Groq's lineup changes.
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Groq's own rate-limit headers use a compound duration format not covered by
# the standard Retry-After header, e.g. "547ms", "1.065s", "8m38.4s". Live-
# observed on every response (not just 429s) as x-ratelimit-reset-tokens /
# x-ratelimit-reset-requests.
_GROQ_DURATION_RE = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?(?:(?P<millis>\d+)ms)?$"
)


def _parse_groq_duration(value: str | None) -> float | None:
    if not value:
        return None
    match = _GROQ_DURATION_RE.match(value.strip())
    if not match or not any(match.groups()):
        return None
    hours = float(match.group("hours") or 0)
    minutes = float(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    millis = float(match.group("millis") or 0)
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _resolve_retry_after(resp: httpx.Response) -> float | None:
    """Prefers the standard `Retry-After` header; falls back to Groq's own
    reset-time headers (using whichever bucket — tokens or requests — is
    closer to reset, i.e. whichever most likely caused this 429)."""
    standard = parse_retry_after_header(resp.headers.get("retry-after"))
    if standard is not None:
        return standard

    candidates = [
        _parse_groq_duration(resp.headers.get(header))
        for header in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
    ]
    candidates = [c for c in candidates if c is not None]
    return min(candidates) if candidates else None


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        base_url: str = GROQ_API_BASE,
        timeout: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        payload: dict = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                return self._parse_response(resp)
            except ProviderRateLimitError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise
                if exc.retry_after is None:
                    wait = DEFAULT_LLM_RETRY_BACKOFF_SECONDS * (attempt + 1)
                elif exc.retry_after > DEFAULT_LLM_RATE_LIMIT_MAX_WAIT_SECONDS:
                    # Groq itself says the window won't reset for a while —
                    # waiting here would just block the user; let
                    # LLMManager fall back to the next provider instead.
                    logger.warning(
                        "Groq rate limited, reported reset in %.1fs (exceeds %.0fs cap) — "
                        "giving up on Groq for this turn: %s",
                        exc.retry_after,
                        DEFAULT_LLM_RATE_LIMIT_MAX_WAIT_SECONDS,
                        exc,
                    )
                    raise
                else:
                    wait = exc.retry_after
                logger.warning(
                    "Groq rate limited (attempt %s/%s), waiting %.2fs (reported reset time): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    wait,
                    exc,
                )
                await asyncio.sleep(wait)
                continue
            except (ProviderConnectionError, ProviderTimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning(
                        "Groq request failed (attempt %s/%s): %s",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
                    await asyncio.sleep(DEFAULT_LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Groq request timed out: {exc}", provider=self.name
                ) from exc
            except httpx.ConnectError as exc:
                raise ProviderConnectionError(
                    f"Could not connect to Groq: {exc}", provider=self.name
                ) from exc

        # Unreachable in practice; satisfies type checkers.
        assert last_error is not None
        raise last_error

    def _parse_response(self, resp: httpx.Response) -> LLMResponse:
        if resp.status_code in (401, 403):
            raise ProviderAuthError(
                "Groq rejected the API key (check GROQ_API_KEY)", provider=self.name
            )
        if resp.status_code == 429:
            raise ProviderRateLimitError(
                "Groq rate limit exceeded",
                provider=self.name,
                retry_after=_resolve_retry_after(resp),
            )
        if resp.status_code >= 500:
            raise ProviderConnectionError(
                f"Groq server error: {resp.status_code}", provider=self.name
            )
        if resp.status_code >= 400:
            raise ProviderResponseError(
                f"Groq request rejected ({resp.status_code}): {resp.text[:300]}",
                provider=self.name,
            )

        try:
            data = resp.json()
            choice = data["choices"][0]
            message = choice["message"]
            return LLMResponse(
                content=message.get("content") or "",
                provider=self.name,
                model=data.get("model", self.model),
                finish_reason=choice.get("finish_reason"),
                tool_calls=message.get("tool_calls"),
                raw=data,
                usage=_extract_usage(data),
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderResponseError(
                f"Unexpected Groq response shape: {exc}", provider=self.name
            ) from exc


def _extract_usage(data: dict) -> TokenUsage | None:
    # Live-verified shape (Aug 2026): data["usage"] = {"prompt_tokens": ...,
    # "completion_tokens": ..., "total_tokens": ..., plus Groq-specific
    # timing fields we don't need here}.
    usage = data.get("usage")
    if not usage:
        return None
    return TokenUsage(
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        total_tokens=usage.get("total_tokens", 0),
    )

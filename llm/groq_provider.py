"""Groq provider — primary LLM (spec.md §11).

Groq exposes an OpenAI-compatible Chat Completions API:
https://console.groq.com/docs/api-reference#chat-create
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from config.defaults import (
    DEFAULT_LLM_MAX_RETRIES,
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
)

logger = logging.getLogger("jarvis.llm.groq")

GROQ_API_BASE = "https://api.groq.com/openai/v1"
# gpt-oss-120b: large context (131k), strong tool-calling support (OpenAI harmony
# format), and available on Ollama Cloud too so provider fallback doesn't change
# model family. Verified against the live /v1/models catalog — re-check
# periodically as Groq's lineup changes.
DEFAULT_MODEL = "openai/gpt-oss-120b"


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
            except (ProviderRateLimitError, ProviderConnectionError, ProviderTimeoutError) as exc:
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
                raise ProviderTimeoutError(f"Groq request timed out: {exc}", provider=self.name) from exc
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
            raise ProviderRateLimitError("Groq rate limit exceeded", provider=self.name)
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
            )
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderResponseError(
                f"Unexpected Groq response shape: {exc}", provider=self.name
            ) from exc

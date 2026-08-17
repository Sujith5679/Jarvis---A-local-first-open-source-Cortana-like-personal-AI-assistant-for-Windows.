"""Ollama Cloud provider — fallback LLM (spec.md §11).

Ollama Cloud speaks the same `/api/chat` contract as local Ollama
(https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion),
authenticated with a bearer API key instead of being open on localhost.

NOTE: Ollama Cloud's hosted API is newer than Groq's and its exact contract
may shift. `base_url` and the request/response shape are isolated in this one
class specifically so they're easy to correct against real credentials
without touching `LLMManager` or any caller.
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

logger = logging.getLogger("jarvis.llm.ollama_cloud")

OLLAMA_CLOUD_API_BASE = "https://ollama.com"
DEFAULT_MODEL = "llama3.3"


class OllamaCloudProvider:
    name = "ollama_cloud"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        *,
        base_url: str = OLLAMA_CLOUD_API_BASE,
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
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(f"{self.base_url}/api/chat", json=payload, headers=headers)
                return self._parse_response(resp)
            except (ProviderRateLimitError, ProviderConnectionError, ProviderTimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning(
                        "Ollama Cloud request failed (attempt %s/%s): %s",
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                    )
                    await asyncio.sleep(DEFAULT_LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                raise
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Ollama Cloud request timed out: {exc}", provider=self.name
                ) from exc
            except httpx.ConnectError as exc:
                raise ProviderConnectionError(
                    f"Could not connect to Ollama Cloud: {exc}", provider=self.name
                ) from exc

        assert last_error is not None
        raise last_error

    def _parse_response(self, resp: httpx.Response) -> LLMResponse:
        if resp.status_code in (401, 403):
            raise ProviderAuthError(
                "Ollama Cloud rejected the API key (check OLLAMA_CLOUD_API_KEY)",
                provider=self.name,
            )
        if resp.status_code == 429:
            raise ProviderRateLimitError("Ollama Cloud rate limit exceeded", provider=self.name)
        if resp.status_code >= 500:
            raise ProviderConnectionError(
                f"Ollama Cloud server error: {resp.status_code}", provider=self.name
            )
        if resp.status_code >= 400:
            raise ProviderResponseError(
                f"Ollama Cloud request rejected ({resp.status_code}): {resp.text[:300]}",
                provider=self.name,
            )

        try:
            data = resp.json()
            message = data["message"]
            return LLMResponse(
                content=message.get("content") or "",
                provider=self.name,
                model=data.get("model", self.model),
                finish_reason="stop" if data.get("done") else None,
                tool_calls=message.get("tool_calls"),
                raw=data,
            )
        except (KeyError, ValueError) as exc:
            raise ProviderResponseError(
                f"Unexpected Ollama Cloud response shape: {exc}", provider=self.name
            ) from exc

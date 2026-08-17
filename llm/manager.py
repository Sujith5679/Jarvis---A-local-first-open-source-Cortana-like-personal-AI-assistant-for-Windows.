"""LLMManager: primary/fallback orchestration across providers (spec.md §11, §32).

Default strategy: Groq primary, Ollama Cloud fallback. Providers are tried in
order; any `ProviderError` (connection, timeout, rate limit, auth, malformed
response) moves on to the next provider, since a single read-only chat
request is safe to retry against a different backend. If every provider
fails, `AllProvidersFailedError` carries every attempt's detail so the caller
can show an actionable error instead of a generic failure.
"""

from __future__ import annotations

import logging

from config.settings import Settings
from llm.base import AllProvidersFailedError, LLMProvider, LLMResponse, ProviderError
from llm.groq_provider import GroqProvider
from llm.ollama_cloud_provider import OllamaCloudProvider

logger = logging.getLogger("jarvis.llm.manager")


class LLMManager:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMManager":
        """Build the default Groq -> Ollama Cloud provider chain from configuration.

        Only configured providers are included. Order matches spec.md §11's
        default strategy (Primary: Groq, Fallback: Ollama Cloud).
        """
        providers: list[LLMProvider] = []
        if settings.has_groq():
            providers.append(GroqProvider(api_key=settings.groq_api_key, model=settings.groq_model))
        if settings.has_ollama_cloud():
            providers.append(
                OllamaCloudProvider(
                    api_key=settings.ollama_cloud_api_key, model=settings.ollama_cloud_model
                )
            )
        return cls(providers)

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        if not self.providers:
            raise AllProvidersFailedError(attempts=[])

        attempts: list[ProviderError] = []
        for provider in self.providers:
            try:
                return await provider.generate(messages, tools=tools)
            except ProviderError as exc:
                logger.warning("Provider %s failed, trying next: %s", provider.name, exc)
                attempts.append(exc)
                continue

        raise AllProvidersFailedError(attempts=attempts)

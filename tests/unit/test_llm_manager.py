from __future__ import annotations

import pytest
from llm.base import (
    AllProvidersFailedError,
    LLMResponse,
    ProviderAuthError,
    ProviderConnectionError,
)
from llm.manager import LLMManager


class _FakeProvider:
    def __init__(self, name: str, *, fails_with: Exception | None = None, reply: str = "ok"):
        self.name = name
        self._fails_with = fails_with
        self._reply = reply
        self.calls = 0

    async def generate(self, messages, tools=None):
        self.calls += 1
        if self._fails_with:
            raise self._fails_with
        return LLMResponse(content=self._reply, provider=self.name, model="fake-model")


@pytest.mark.asyncio
async def test_primary_success_no_fallback():
    primary = _FakeProvider("primary", reply="primary reply")
    fallback = _FakeProvider("fallback", reply="fallback reply")
    manager = LLMManager([primary, fallback])

    result = await manager.generate([{"role": "user", "content": "hi"}])

    assert result.content == "primary reply"
    assert result.provider == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_connection_error_falls_back():
    primary = _FakeProvider(
        "primary", fails_with=ProviderConnectionError("down", provider="primary")
    )
    fallback = _FakeProvider("fallback", reply="fallback reply")
    manager = LLMManager([primary, fallback])

    result = await manager.generate([{"role": "user", "content": "hi"}])

    assert result.content == "fallback reply"
    assert result.provider == "fallback"


@pytest.mark.asyncio
async def test_auth_error_falls_back():
    """Matches the demo requirement: an invalid GROQ_API_KEY should fall through
    to Ollama Cloud rather than surfacing a hard failure."""
    primary = _FakeProvider("primary", fails_with=ProviderAuthError("bad key", provider="primary"))
    fallback = _FakeProvider("fallback", reply="fallback reply")
    manager = LLMManager([primary, fallback])

    result = await manager.generate([{"role": "user", "content": "hi"}])

    assert result.provider == "fallback"


@pytest.mark.asyncio
async def test_all_providers_failing_raises_with_details():
    primary = _FakeProvider(
        "primary", fails_with=ProviderConnectionError("down", provider="primary")
    )
    fallback = _FakeProvider(
        "fallback", fails_with=ProviderConnectionError("also down", provider="fallback")
    )
    manager = LLMManager([primary, fallback])

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await manager.generate([{"role": "user", "content": "hi"}])

    assert len(excinfo.value.attempts) == 2
    message = str(excinfo.value)
    assert "primary" in message
    assert "fallback" in message


@pytest.mark.asyncio
async def test_no_providers_configured_raises_actionable_error():
    manager = LLMManager([])

    with pytest.raises(AllProvidersFailedError) as excinfo:
        await manager.generate([{"role": "user", "content": "hi"}])

    assert "GROQ_API_KEY" in str(excinfo.value)

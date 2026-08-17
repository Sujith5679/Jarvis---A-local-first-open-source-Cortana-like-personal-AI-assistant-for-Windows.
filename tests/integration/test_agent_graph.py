from __future__ import annotations

import pytest

from agent.graph import Agent
from llm.base import AllProvidersFailedError, LLMResponse
from llm.manager import LLMManager
from storage.repositories import conversations as conv_repo


class _StubProvider:
    name = "stub"

    def __init__(self, reply: str = "Hello! How can I help?"):
        self.reply = reply
        self.received_messages: list[dict] | None = None

    async def generate(self, messages, tools=None):
        self.received_messages = messages
        return LLMResponse(content=self.reply, provider=self.name, model="stub-model")


class _AlwaysFailingProvider:
    name = "broken"

    async def generate(self, messages, tools=None):
        from llm.base import ProviderConnectionError

        raise ProviderConnectionError("nope", provider=self.name)


@pytest.mark.asyncio
async def test_run_turn_persists_and_returns_response(real_db):
    stub = _StubProvider(reply="42 is the answer.")
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "What is the answer?")

    assert state["response"] == "42 is the answer."
    assert state["error"] is None

    messages = conv_repo.get_messages(conv_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What is the answer?"
    assert messages[1]["content"] == "42 is the answer."


@pytest.mark.asyncio
async def test_run_turn_includes_system_prompt_and_history(real_db):
    stub = _StubProvider()
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    await agent.run_turn(conv_id, "first message")
    await agent.run_turn(conv_id, "second message")

    assert stub.received_messages[0]["role"] == "system"
    contents = [m["content"] for m in stub.received_messages]
    assert "first message" in contents
    assert "second message" in contents


@pytest.mark.asyncio
async def test_run_turn_surfaces_provider_failure_without_crashing(real_db):
    agent = Agent(llm_manager=LLMManager([_AlwaysFailingProvider()]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "hello")

    assert state["response"] is None
    assert state["error"] is not None

    # The user's message is still persisted even though generation failed —
    # JARVIS must never silently drop what the user said.
    messages = conv_repo.get_messages(conv_id)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

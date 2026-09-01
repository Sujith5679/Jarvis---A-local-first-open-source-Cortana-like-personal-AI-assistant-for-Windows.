from __future__ import annotations

import pytest
from agent.graph import Agent
from agent.prompts import MEMORY_SECTION_HEADER
from llm.base import LLMResponse, TokenUsage
from llm.manager import LLMManager
from storage.repositories import conversations as conv_repo
from storage.repositories import usage as usage_repo


class _StubProvider:
    name = "stub"

    def __init__(self, reply: str = "Hello! How can I help?", usage: TokenUsage | None = None):
        self.reply = reply
        self.usage = usage
        self.received_messages: list[dict] | None = None

    async def generate(self, messages, tools=None):
        self.received_messages = messages
        return LLMResponse(
            content=self.reply, provider=self.name, model="stub-model", usage=self.usage
        )


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
async def test_run_turn_injects_remembered_facts_into_system_prompt(real_db):
    """A fact remembered in one conversation must be visible in a
    *different* conversation's system prompt — the whole point of
    persistent memory vs. plain per-conversation history."""
    from storage.repositories import memories as memories_repo

    memories_repo.create_memory("The user prefers metric units.", memory_type="preference")

    stub = _StubProvider()
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    other_conv_id = conv_repo.create_conversation()  # a conversation that never saw this fact

    await agent.run_turn(other_conv_id, "what's the weather like")

    system_message = stub.received_messages[0]
    assert system_message["role"] == "system"
    assert "The user prefers metric units." in system_message["content"]


@pytest.mark.asyncio
async def test_run_turn_without_memories_has_no_memory_section(real_db):
    stub = _StubProvider()
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    await agent.run_turn(conv_id, "hello")

    assert MEMORY_SECTION_HEADER not in stub.received_messages[0]["content"]


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


@pytest.mark.asyncio
async def test_run_turn_records_llm_usage_when_provider_reports_it(real_db):
    stub = _StubProvider(
        reply="42 is the answer.",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    await agent.run_turn(conv_id, "What is the answer?")

    totals = usage_repo.get_session_totals(str(conv_id))
    assert totals["call_count"] == 1
    assert totals["prompt_tokens"] == 10
    assert totals["completion_tokens"] == 5
    assert totals["total_tokens"] == 15


@pytest.mark.asyncio
async def test_run_turn_skips_usage_recording_when_provider_reports_none(real_db):
    stub = _StubProvider(reply="no usage here", usage=None)
    agent = Agent(llm_manager=LLMManager([stub]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    await agent.run_turn(conv_id, "hello")

    totals = usage_repo.get_session_totals(str(conv_id))
    assert totals["call_count"] == 0

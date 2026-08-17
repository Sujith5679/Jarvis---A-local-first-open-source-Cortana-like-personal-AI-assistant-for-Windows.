from __future__ import annotations

import json

import pytest
from agent.graph import Agent
from llm.base import LLMResponse
from llm.manager import LLMManager
from storage.repositories import conversations as conv_repo


class _ScriptedProvider:
    """Replays a fixed sequence of LLMResponses, one per generate() call —
    lets a test script a multi-step tool-calling conversation deterministically."""

    name = "scripted"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.seen_messages: list[list[dict]] = []

    async def generate(self, messages, tools=None):
        self.seen_messages.append(messages)
        if not self._responses:
            raise AssertionError("Scripted provider ran out of responses")
        return self._responses.pop(0)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


@pytest.mark.asyncio
async def test_agent_executes_real_search_tool_and_extracts_citations(
    indexed_sample_folder, real_db
):
    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[
                _tool_call("call_1", "search_files", {"query": "fraud detection approach"})
            ],
        ),
        LLMResponse(
            content="I found the ClaimsX report, which describes the fraud detection approach.",
            provider="scripted",
            model="x",
        ),
    ]
    provider = _ScriptedProvider(responses)
    agent = Agent(llm_manager=LLMManager([provider]), settings=real_db)

    conv_id = conv_repo.create_conversation()
    state = await agent.run_turn(conv_id, "What was the fraud detection approach in ClaimsX?")

    assert state["error"] is None
    assert "fraud detection" in state["response"].lower()
    assert len(state["tool_calls"]) == 1
    assert state["tool_calls"][0]["name"] == "search_files"
    assert state["tool_results"][0]["result"]["results"], "expected real search hits"
    assert any(c["filename"] == "claimsx_report.txt" for c in state["citations"])

    # The second LLM call must have seen the tool's result as a role="tool" message.
    second_call_messages = provider.seen_messages[1]
    assert any(m.get("role") == "tool" for m in second_call_messages)

    # Persisted history holds only the user question + final answer, not the
    # intermediate tool exchange (see agent/graph.py's module docstring).
    persisted = conv_repo.get_messages(conv_id)
    assert [m["role"] for m in persisted] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_agent_handles_unknown_tool_name_gracefully(indexed_sample_folder, real_db):
    responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call("call_1", "delete_everything", {})],
        ),
        LLMResponse(
            content="I can't do that, but here's what I can help with.",
            provider="scripted",
            model="x",
        ),
    ]
    agent = Agent(llm_manager=LLMManager([_ScriptedProvider(responses)]), settings=real_db)
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "Delete everything")

    assert state["error"] is None
    assert state["tool_results"][0]["result"]["error"] == "Unknown tool: delete_everything"


@pytest.mark.asyncio
async def test_agent_stops_after_max_tool_steps(indexed_sample_folder, real_db):
    # A provider that always proposes another tool call, never a final answer.
    infinite_responses = [
        LLMResponse(
            content="",
            provider="scripted",
            model="x",
            tool_calls=[_tool_call(f"call_{i}", "search_files", {"query": "x"})],
        )
        for i in range(20)
    ]
    agent = Agent(
        llm_manager=LLMManager([_ScriptedProvider(infinite_responses)]),
        settings=real_db,
        max_tool_steps=3,
    )
    conv_id = conv_repo.create_conversation()

    state = await agent.run_turn(conv_id, "loop forever")

    assert state["error"] is not None
    assert "maximum number of tool steps" in state["error"]
    assert len(state["tool_calls"]) == 3

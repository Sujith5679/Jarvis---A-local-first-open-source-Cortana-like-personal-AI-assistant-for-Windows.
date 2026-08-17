"""Agent state (spec.md §12), exactly as specified."""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict):
    user_message: str
    conversation_id: str
    intent: str | None
    plan: list[dict]
    tool_calls: list[dict]
    tool_results: list[dict]
    retrieved_context: list[dict]
    citations: list[dict]
    response: str | None
    requires_confirmation: bool
    confirmation_request: dict | None
    error: str | None


def new_state(user_message: str, conversation_id: str) -> AgentState:
    """Construct a fresh AgentState for one conversational turn."""
    return AgentState(
        user_message=user_message,
        conversation_id=conversation_id,
        intent=None,
        plan=[],
        tool_calls=[],
        tool_results=[],
        retrieved_context=[],
        citations=[],
        response=None,
        requires_confirmation=False,
        confirmation_request=None,
        error=None,
    )

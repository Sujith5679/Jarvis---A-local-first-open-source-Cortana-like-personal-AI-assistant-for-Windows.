"""Tool contract and registry (spec.md §13).

Every tool the agent can call is registered here with a typed input schema,
a permission level, and whether it requires user confirmation. The LLM only
ever *proposes* a tool call by name + arguments — this registry (called from
application code, not from inside a prompt) is what actually looks up and
executes the tool, and `security/permissions.py` (added alongside the first
MEDIUM/HIGH-risk tool) is what decides whether it's allowed to run
unconfirmed. This split is required by spec.md §54: permission checks must
happen in application code, never only inside the LLM prompt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass
class ToolMetadata:
    name: str
    description: str
    requires_confirmation: bool
    risk_level: RiskLevel
    timeout_seconds: float


@dataclass
class Tool:
    metadata: ToolMetadata
    # JSON-schema-shaped parameters, as required by OpenAI-style function calling.
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]

    @property
    def name(self) -> str:
        return self.metadata.name

    def to_llm_schema(self) -> dict[str, Any]:
        """OpenAI/Groq-compatible tool-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": self.input_schema,
            },
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        return await self.handler(**kwargs)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def llm_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_llm_schema() for tool in self._tools.values()]


# Process-wide default registry. Individual tool modules (file_search,
# file_reader, notes, tasks, ...) register themselves into this via their
# own `register(registry)` function, called once from app bootstrap.
default_registry = ToolRegistry()

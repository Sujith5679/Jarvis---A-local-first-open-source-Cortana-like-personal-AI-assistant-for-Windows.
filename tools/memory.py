"""Persistent cross-conversation memory tools (spec.md §30).

remember_fact/recall_facts = LOW (matches create_note/search_notes — just
structured personal data, same category); forget_fact = HIGH (matches
delete_note — permanent, cannot be undone).

spec.md §30's rule is enforced by never calling this on the agent's own
initiative anywhere else in the codebase: "Only store permanent memories
when: User explicitly asks JARVIS to remember something." The system
prompt (agent/prompts.py's BASE_SYSTEM_PROMPT) tells the LLM this
explicitly too, so it doesn't call remember_fact speculatively.
"""

from __future__ import annotations

from typing import Any

from storage.repositories import memories as memories_repo

from tools.registry import Tool, ToolMetadata


async def remember_fact_handler(
    content: str, memory_type: str = memories_repo.DEFAULT_MEMORY_TYPE
) -> dict[str, Any]:
    if not content or not content.strip():
        return {"error": "Cannot remember an empty fact."}
    if memory_type not in memories_repo.VALID_MEMORY_TYPES:
        return {
            "error": f"Invalid memory_type {memory_type!r}. "
            f"Must be one of: {', '.join(memories_repo.VALID_MEMORY_TYPES)}."
        }
    memory_id = memories_repo.create_memory(content, memory_type=memory_type)
    return {"memory_id": memory_id, "content": content, "memory_type": memory_type}


async def recall_facts_handler(query: str | None = None) -> dict[str, Any]:
    if query:
        results = memories_repo.search_memories(query)
    else:
        from config.defaults import DEFAULT_MAX_INJECTED_MEMORIES

        results = memories_repo.list_memories(limit=DEFAULT_MAX_INJECTED_MEMORIES)
    return {
        "results": [
            {"memory_id": m["id"], "content": m["content"], "memory_type": m["memory_type"]}
            for m in results
        ]
    }


async def forget_fact_handler(memory_id: int) -> dict[str, Any]:
    ok = memories_repo.delete_memory(memory_id)
    if not ok:
        return {"error": f"No (deletable) memory found with id {memory_id}."}
    return {"memory_id": memory_id, "forgotten": True}


REMEMBER_FACT = Tool(
    metadata=ToolMetadata(
        name="remember_fact",
        description=(
            "Permanently remember a fact about the user or their preferences, so it's "
            "available in future conversations too — not just this one. Only call this when "
            "the user explicitly asks you to remember something; never store facts from a "
            "conversation on your own initiative."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact to remember, in plain language.",
            },
            "memory_type": {
                "type": "string",
                "enum": list(memories_repo.VALID_MEMORY_TYPES),
                "default": memories_repo.DEFAULT_MEMORY_TYPE,
                "description": (
                    "'preference' for stated preferences, 'knowledge' for everything else."
                ),
            },
        },
        "required": ["content"],
    },
    handler=remember_fact_handler,
)

RECALL_FACTS = Tool(
    metadata=ToolMetadata(
        name="recall_facts",
        description=(
            "List or search facts previously remembered about the user (see remember_fact). "
            "Most remembered facts are already included in your context automatically — use "
            "this to check what's remembered, search for something specific, or look beyond "
            "what's already in context."
        ),
        requires_confirmation=False,
        risk_level="low",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional keyword filter; omit to list the most recent facts.",
            }
        },
    },
    handler=recall_facts_handler,
)

FORGET_FACT = Tool(
    metadata=ToolMetadata(
        name="forget_fact",
        description="Permanently forget a previously remembered fact by id. This cannot be undone.",
        requires_confirmation=True,
        risk_level="high",
        timeout_seconds=5.0,
    ),
    input_schema={
        "type": "object",
        "properties": {"memory_id": {"type": "integer"}},
        "required": ["memory_id"],
    },
    handler=forget_fact_handler,
)


def register(registry) -> None:
    registry.register(REMEMBER_FACT)
    registry.register(RECALL_FACTS)
    registry.register(FORGET_FACT)

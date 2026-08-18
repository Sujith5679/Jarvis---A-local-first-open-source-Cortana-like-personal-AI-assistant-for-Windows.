"""LangGraph agent orchestration (spec.md §12).

Graph: preprocess -> generate (tool-selection / permission-check / tool-
execution / observation loop lives inside this node) -> audit -> END.

Tool-calling messages (assistant tool_calls + tool results) are kept local
to the in-memory `llm_messages` list for the duration of one turn and are
NOT written to the `messages` table — only the user's question and the
final assistant answer are persisted as conversation history. This sidesteps
having to reconstruct provider-specific tool-call message shapes when
rebuilding history for a *later* turn (Groq/OpenAI and Ollama's native API
don't necessarily agree on that shape) and matches AgentState's own design:
`tool_calls`/`tool_results` are turn-scoped, `messages` is durable history.

The provider that serves the first LLM call of a turn is pinned for the rest
of that turn's tool-loop, so a mid-turn Groq<->Ollama Cloud fallback can
never mix two providers' tool-call formats in one exchange. If the pinned
provider then fails mid-loop, we fall back through LLMManager fresh (small
risk of a format mismatch in that rare case, preferred over crashing the
turn).

When the LLM proposes a HIGH-risk tool call (e.g. delete_note), the loop
stops immediately with `requires_confirmation=True` and a
`confirmation_request` describing what was proposed — the tool is NOT run.
The caller (UI) shows that to the user and, on a decision, calls
`Agent.confirm_and_execute()` directly: it does not re-enter the LLM loop or
try to reconstruct the paused conversation state, it just runs (or skips)
exactly that one tool and appends a deterministic confirmation message to
history. This keeps "was this actually confirmed by the user" unambiguous
rather than trusting the LLM to re-propose the same call faithfully.
"""

from __future__ import annotations

import asyncio
import json
import logging

from config.defaults import (
    DEFAULT_GLOBAL_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_MAX_TOOL_STEPS,
)
from config.settings import Settings, get_settings
from langgraph.graph import END, StateGraph
from llm.base import AllProvidersFailedError, LLMResponse, ProviderError
from llm.manager import LLMManager
from security.audit import log_event
from security.permissions import check_permission
from storage.repositories import conversations as conv_repo
from tools import (
    file_listing,
    file_reader,
    file_search,
    file_writer,
    notes,
    reminders,
    tasks,
    web_reader,
    web_search,
)
from tools.registry import Tool, ToolRegistry

from agent.prompts import build_system_prompt
from agent.state import AgentState, new_state

logger = logging.getLogger("jarvis.agent.graph")

MAX_HISTORY_MESSAGES = 20
TOOL_RESULT_MAX_CHARS = 4000


def build_default_tool_registry() -> ToolRegistry:
    """Phase 2/3/4 tools. Later phases (windows) add their own
    `register(registry)` calls here without touching the rest of this
    module."""
    registry = ToolRegistry()
    file_search.register(registry)
    file_reader.register(registry)
    file_listing.register(registry)
    file_writer.register(registry)
    notes.register(registry)
    tasks.register(registry)
    reminders.register(registry)
    web_search.register(registry)
    web_reader.register(registry)
    return registry


def _normalize_tool_calls(raw: list[dict] | None) -> list[dict]:
    """Normalize provider-specific tool_call shapes into
    {id, name, arguments (dict)}. Handles both OpenAI-style (arguments as a
    JSON string) and Ollama-native-style (arguments already a dict)."""
    if not raw:
        return []
    normalized = []
    for i, call in enumerate(raw):
        fn = call.get("function", call)
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                args = {}
        elif not isinstance(args, dict):
            args = {}
        normalized.append({"id": call.get("id") or f"call_{i}", "name": name, "arguments": args})
    return normalized


def _extract_citations(tool_results: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for entry in tool_results:
        result = entry.get("result") or {}
        if isinstance(result.get("results"), list):
            for r in result["results"]:
                if "filename" in r:  # search_files shape
                    citations.append(
                        {
                            "filename": r.get("filename"),
                            "path": r.get("path"),
                            "page": r.get("page"),
                            "section": r.get("section"),
                        }
                    )
                elif "url" in r:  # web_search shape
                    citations.append({"title": r.get("title"), "url": r.get("url")})
        elif result.get("filename"):  # read_file shape
            citations.append(
                {
                    "filename": result.get("filename"),
                    "path": result.get("path"),
                    "page": result.get("page"),
                    "section": result.get("section"),
                }
            )
        elif result.get("url"):  # open_webpage shape
            citations.append(
                {
                    "title": result.get("title"),
                    "url": result.get("url"),
                    "domain": result.get("domain"),
                    "retrieved_at": result.get("retrieved_at"),
                }
            )
    return citations


def _summarize_confirmed_result(tool_name: str, arguments: dict, result: dict) -> str:
    """Deterministic (non-LLM) confirmation message. Only ever describes what
    the tool actually returned — never phrased as if the LLM is guessing,
    per spec.md §55 ("Never claim success unless the tool confirmed it")."""
    if tool_name == "delete_note":
        return f"Done — deleted note #{arguments.get('note_id')}."
    if tool_name == "delete_task":
        return f"Done — deleted task #{arguments.get('task_id')}."
    if tool_name == "write_file":
        verb = "Overwrote" if result.get("overwritten") else "Saved"
        return f"Done — {verb} {result.get('bytes_written', 0)} bytes to {result.get('path')}."
    return f"Done — {tool_name} completed: {result}"


class Agent:
    def __init__(
        self,
        llm_manager: LLMManager,
        settings: Settings | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_steps: int = DEFAULT_MAX_TOOL_STEPS,
    ) -> None:
        self.llm_manager = llm_manager
        self.settings = settings or get_settings()
        self.tool_registry = (
            tool_registry if tool_registry is not None else build_default_tool_registry()
        )
        self.max_tool_steps = max_tool_steps
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("preprocess", self._preprocess)
        graph.add_node("generate", self._generate)
        graph.add_node("audit", self._audit)
        graph.set_entry_point("preprocess")
        graph.add_edge("preprocess", "generate")
        graph.add_edge("generate", "audit")
        graph.add_edge("audit", END)
        return graph.compile()

    async def _preprocess(self, state: AgentState) -> AgentState:
        state["user_message"] = state["user_message"].strip()
        return state

    async def _call_llm(
        self, llm_messages: list[dict], tools: list[dict], pinned_provider_name: str | None
    ) -> tuple[LLMResponse, str]:
        """Returns (response, provider_name_used). Prefers the pinned provider
        (see module docstring); falls back through LLMManager if it fails."""
        if pinned_provider_name:
            provider = next(
                (p for p in self.llm_manager.providers if p.name == pinned_provider_name), None
            )
            if provider is not None:
                try:
                    response = await provider.generate(llm_messages, tools=tools)
                    return response, provider.name
                except ProviderError as exc:
                    logger.warning(
                        "Pinned provider %s failed mid-turn, falling back fresh: %s",
                        pinned_provider_name,
                        exc,
                    )
        response = await self.llm_manager.generate(llm_messages, tools=tools)
        return response, response.provider

    async def _run_tool_loop(self, state: AgentState, llm_messages: list[dict]) -> None:
        tool_schemas = self.tool_registry.llm_schemas()
        pinned_provider: str | None = None

        for _step in range(self.max_tool_steps):
            try:
                response, pinned_provider = await self._call_llm(
                    llm_messages, tool_schemas, pinned_provider
                )
            except AllProvidersFailedError as exc:
                state["error"] = str(exc)
                return

            tool_calls = _normalize_tool_calls(response.tool_calls)
            if not tool_calls:
                state["response"] = response.content
                return

            llm_messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"]),
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                state["tool_calls"].append({"name": tc["name"], "arguments": tc["arguments"]})
                result = await self._execute_tool(state, tc["name"], tc["arguments"])
                state["tool_results"].append({"name": tc["name"], "result": result})

                if state["requires_confirmation"]:
                    # Stop entirely rather than feed this back to the LLM and
                    # keep going — the turn is paused until the UI calls
                    # confirm_and_execute() with the user's decision.
                    return

                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result)[:TOOL_RESULT_MAX_CHARS],
                    }
                )

        state["error"] = (
            f"Reached the maximum number of tool steps ({self.max_tool_steps}) "
            "without a final answer."
        )

    async def _execute_tool(self, state: AgentState, name: str, arguments: dict) -> dict:
        tool: Tool | None = self.tool_registry.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}

        decision = check_permission(tool)
        if not decision.allowed:
            state["requires_confirmation"] = True
            state["confirmation_request"] = {
                "tool": name,
                "arguments": arguments,
                "reason": decision.reason,
            }
            return {"error": decision.reason}

        try:
            return await asyncio.wait_for(
                tool.execute(**arguments), timeout=tool.metadata.timeout_seconds
            )
        except TimeoutError:
            return {"error": f"Tool '{name}' timed out after {tool.metadata.timeout_seconds}s."}
        except Exception as exc:
            logger.exception("Tool '%s' raised an unexpected error", name)
            return {"error": f"Tool '{name}' failed: {exc}"}

    async def _generate(self, state: AgentState) -> AgentState:
        conversation_id = int(state["conversation_id"])
        conv_repo.add_message(conversation_id, "user", state["user_message"])

        history = conv_repo.get_messages(conversation_id, limit=MAX_HISTORY_MESSAGES)
        llm_messages = [{"role": "system", "content": build_system_prompt(self.settings)}]
        llm_messages += conv_repo.to_llm_messages(history)

        try:
            await asyncio.wait_for(
                self._run_tool_loop(state, llm_messages),
                timeout=DEFAULT_GLOBAL_REQUEST_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            state["error"] = "The request took too long and was cancelled."

        state["citations"] = _extract_citations(state["tool_results"])

        if state["response"] is not None:
            conv_repo.add_message(
                conversation_id,
                "assistant",
                state["response"],
                citations=state["citations"] or None,
            )

        return state

    async def _audit(self, state: AgentState) -> AgentState:
        status = "success" if state["error"] is None else "error"
        if state["requires_confirmation"]:
            status = "pending_confirmation"
        log_event(
            "chat_turn",
            status=status,
            session_id=state["conversation_id"],
            input_summary=state["user_message"][:200],
            result_summary=(state["response"] or state["error"] or "")[:200],
        )
        for entry in state["tool_results"]:
            result = entry.get("result") or {}
            log_event(
                "tool_execution",
                tool=entry.get("name"),
                status="error" if result.get("error") else "success",
                session_id=state["conversation_id"],
                input_summary=str(entry.get("name")),
                result_summary=str(result)[:300],
            )
        return state

    async def run_turn(self, conversation_id: int, user_message: str) -> AgentState:
        state = new_state(user_message, str(conversation_id))
        return await self._graph.ainvoke(state)  # type: ignore[return-value]

    async def confirm_and_execute(
        self, conversation_id: int, tool_name: str, arguments: dict, *, approved: bool
    ) -> AgentState:
        """Resolves a paused `requires_confirmation` turn. Does not go back
        through the LLM — runs (or skips) exactly the one proposed tool call
        and appends a deterministic result message to conversation history.
        See the module docstring for why."""
        state = new_state("", str(conversation_id))

        tool = self.tool_registry.get(tool_name)
        if tool is None:
            state["error"] = f"Unknown tool: {tool_name}"
            return state

        if not approved:
            message = f"Okay, I won't run {tool_name}."
            conv_repo.add_message(conversation_id, "assistant", message)
            state["response"] = message
            log_event(
                "tool_confirmation",
                status="cancelled",
                tool=tool_name,
                session_id=str(conversation_id),
                input_summary=str(arguments),
            )
            return state

        try:
            result = await asyncio.wait_for(
                tool.execute(**arguments), timeout=tool.metadata.timeout_seconds
            )
        except TimeoutError:
            result = {
                "error": f"Tool '{tool_name}' timed out after {tool.metadata.timeout_seconds}s."
            }
        except Exception as exc:
            logger.exception("Confirmed tool '%s' raised an unexpected error", tool_name)
            result = {"error": f"Tool '{tool_name}' failed: {exc}"}

        state["tool_calls"].append({"name": tool_name, "arguments": arguments})
        state["tool_results"].append({"name": tool_name, "result": result})
        state["citations"] = _extract_citations(state["tool_results"])

        if result.get("error"):
            state["error"] = result["error"]
            message = f"I couldn't complete that: {result['error']}"
        else:
            message = _summarize_confirmed_result(tool_name, arguments, result)

        conv_repo.add_message(
            conversation_id, "assistant", message, citations=state["citations"] or None
        )
        state["response"] = message

        log_event(
            "tool_confirmation",
            status="error" if result.get("error") else "success",
            tool=tool_name,
            session_id=str(conversation_id),
            input_summary=str(arguments),
            result_summary=str(result)[:300],
        )
        return state


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    return Agent(llm_manager=LLMManager.from_settings(settings), settings=settings)

"""LangGraph agent orchestration (spec.md §12).

Phase 1 slice of the full graph: preprocess -> generate response -> audit ->
END. No tools yet — tool selection / permission-check / execution /
observation nodes are inserted between `generate` and `audit` in Phase 2
without changing this module's public shape (`Agent.run_turn`).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from agent.prompts import build_system_prompt
from agent.state import AgentState, new_state
from config.settings import Settings, get_settings
from llm.base import AllProvidersFailedError
from llm.manager import LLMManager
from security.audit import log_event
from storage.repositories import conversations as conv_repo

MAX_HISTORY_MESSAGES = 20


class Agent:
    """Wraps the compiled LangGraph so callers only ever deal with `run_turn`."""

    def __init__(self, llm_manager: LLMManager, settings: Settings | None = None) -> None:
        self.llm_manager = llm_manager
        self.settings = settings or get_settings()
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

    async def _generate(self, state: AgentState) -> AgentState:
        conversation_id = int(state["conversation_id"])
        conv_repo.add_message(conversation_id, "user", state["user_message"])

        history = conv_repo.get_messages(conversation_id, limit=MAX_HISTORY_MESSAGES)
        llm_messages = [{"role": "system", "content": build_system_prompt(self.settings)}]
        llm_messages += conv_repo.to_llm_messages(history)

        try:
            response = await self.llm_manager.generate(llm_messages)
        except AllProvidersFailedError as exc:
            state["error"] = str(exc)
            state["response"] = None
            return state

        state["response"] = response.content
        conv_repo.add_message(conversation_id, "assistant", response.content)
        return state

    async def _audit(self, state: AgentState) -> AgentState:
        log_event(
            "chat_turn",
            status="success" if state["error"] is None else "error",
            session_id=state["conversation_id"],
            input_summary=state["user_message"][:200],
            result_summary=(state["response"] or state["error"] or "")[:200],
        )
        return state

    async def run_turn(self, conversation_id: int, user_message: str) -> AgentState:
        state = new_state(user_message, str(conversation_id))
        return await self._graph.ainvoke(state)  # type: ignore[return-value]


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    return Agent(llm_manager=LLMManager.from_settings(settings), settings=settings)

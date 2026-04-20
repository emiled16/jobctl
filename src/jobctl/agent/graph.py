"""Compile the LangGraph graph that powers jobctl's chat runtime."""

from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.graph import END, StateGraph

from jobctl.agent.nodes.chat_node import chat_node
from jobctl.agent.nodes.confirm_node import wait_for_confirmation_node
from jobctl.agent.nodes.graph_qa_node import graph_qa_node
from jobctl.agent.router import route
from jobctl.agent.state import AgentState
from jobctl.core.events import AsyncEventBus
from jobctl.llm.base import LLMProvider


def build_graph(
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    bus: AsyncEventBus,
) -> Any:
    """Return a compiled LangGraph graph bound to the given dependencies."""

    def _chat(state: AgentState) -> AgentState:
        return chat_node(state, provider=provider, bus=bus)

    def _graph_qa(state: AgentState) -> AgentState:
        return graph_qa_node(state, provider=provider, conn=conn, bus=bus)

    async def _wait(state: AgentState) -> AgentState:
        return await wait_for_confirmation_node(state, bus=bus)

    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("chat_node", _chat)
    graph.add_node("graph_qa_node", _graph_qa)
    graph.add_node("wait_for_confirmation", _wait)

    graph.set_conditional_entry_point(
        route,
        {
            "chat_node": "chat_node",
            "graph_qa_node": "graph_qa_node",
            "wait_for_confirmation": "wait_for_confirmation",
            # M3+: ingest/curate/apply nodes are added dynamically later.
            "ingest_node": "chat_node",
            "curate_node": "chat_node",
            "apply_node": "chat_node",
        },
    )
    graph.add_edge("chat_node", END)
    graph.add_edge("graph_qa_node", END)
    graph.add_edge("wait_for_confirmation", END)

    return graph.compile()


__all__ = ["build_graph"]

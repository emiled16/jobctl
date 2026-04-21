"""Compile the LangGraph graph that powers jobctl's chat runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from jobctl.agent.nodes.apply_node import apply_node
from jobctl.agent.nodes.chat_node import chat_node
from jobctl.agent.nodes.confirm_node import wait_for_confirmation_node
from jobctl.agent.nodes.curate_node import curate_node
from jobctl.agent.nodes.graph_qa_node import graph_qa_node
from jobctl.agent.nodes.ingest_node import ingest_node
from jobctl.agent.nodes.refinement_node import refinement_node
from jobctl.agent.router import route
from jobctl.agent.state import AgentState
from jobctl.config import JobctlConfig
from jobctl.core.events import AsyncEventBus
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.curation.proposals import CurationProposalStore
from jobctl.llm.base import LLMProvider
from jobctl.rag.store import VectorStore


def build_graph(
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    bus: AsyncEventBus,
    store: BackgroundJobStore | None = None,
    runner: BackgroundJobRunner | None = None,
    proposal_store: CurationProposalStore | None = None,
    config: JobctlConfig | None = None,
    db_path: Path | None = None,
    vector_store: VectorStore | None = None,
) -> Any:
    """Return a compiled LangGraph graph bound to the given dependencies."""

    def _chat(state: AgentState) -> AgentState:
        return chat_node(state, provider=provider, bus=bus)

    def _graph_qa(state: AgentState) -> AgentState:
        if vector_store is None:
            return chat_node(state, provider=provider, bus=bus)
        return graph_qa_node(state, provider=provider, conn=conn, vector_store=vector_store, bus=bus)

    async def _wait(state: AgentState) -> AgentState:
        return await wait_for_confirmation_node(state, bus=bus)

    def _ingest(state: AgentState) -> AgentState:
        if store is None or runner is None:
            # Fall back to chat if background infra is missing.
            return chat_node(state, provider=provider, bus=bus)
        return ingest_node(
            state,
            provider=provider,
            conn=conn,
            store=store,
            runner=runner,
            bus=bus,
            db_path=db_path,
            config=config,
            vector_store=vector_store,
        )

    graph: StateGraph[AgentState] = StateGraph(AgentState)
    graph.add_node("chat_node", _chat)
    graph.add_node("graph_qa_node", _graph_qa)
    graph.add_node("wait_for_confirmation", _wait)
    graph.add_node("ingest_node", _ingest)

    def _refinement(state: AgentState) -> AgentState:
        if vector_store is None:
            return chat_node(state, provider=provider, bus=bus)
        return refinement_node(
            state,
            provider=provider,
            conn=conn,
            vector_store=vector_store,
            bus=bus,
        )

    graph.add_node("refinement_node", _refinement)

    def _curate(state: AgentState) -> AgentState:
        if vector_store is None:
            return chat_node(state, provider=provider, bus=bus)
        proposal_store_local = proposal_store or CurationProposalStore(conn)
        return curate_node(
            state,
            provider=provider,
            conn=conn,
            proposal_store=proposal_store_local,
            bus=bus,
            vector_store=vector_store,
        )

    graph.add_node("curate_node", _curate)

    def _apply(state: AgentState) -> AgentState:
        if store is None or runner is None or config is None:
            return chat_node(state, provider=provider, bus=bus)
        return apply_node(
            state,
            provider=provider,
            conn=conn,
            config=config,
            store=store,
            runner=runner,
            bus=bus,
            db_path=db_path,
            vector_store=vector_store,
        )

    graph.add_node("apply_node", _apply)

    graph.set_conditional_entry_point(
        route,
        {
            "chat_node": "chat_node",
            "graph_qa_node": "graph_qa_node",
            "wait_for_confirmation": "wait_for_confirmation",
            "ingest_node": "ingest_node",
            "refinement_node": "refinement_node",
            "curate_node": "curate_node",
            "apply_node": "apply_node",
        },
    )
    graph.add_edge("chat_node", END)
    graph.add_edge("graph_qa_node", END)
    graph.add_edge("wait_for_confirmation", END)
    graph.add_edge("ingest_node", END)
    graph.add_edge("refinement_node", END)
    graph.add_edge("curate_node", END)
    graph.add_edge("apply_node", END)

    return graph.compile()


__all__ = ["build_graph"]

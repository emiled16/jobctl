"""Typed agent state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from jobctl.llm.base import Message

AgentMode = Literal["chat", "ingest", "curate", "apply", "graph_qa"]


class Confirmation(TypedDict):
    question: str
    confirm_id: str


class Coverage(TypedDict, total=False):
    nodes_by_type: dict[str, int]
    orphans: list[dict[str, Any]]
    suggestions: list[str]
    total_nodes: int
    total_edges: int


class AgentState(TypedDict, total=False):
    messages: list[Message]
    mode: AgentMode
    pending_confirmation: Confirmation | None
    coverage: Coverage | None
    last_tool_result: dict[str, Any] | None
    session_id: str


def new_state(session_id: str) -> AgentState:
    """Build an empty ``AgentState`` seeded with the session id."""
    return AgentState(
        messages=[],
        mode="chat",
        pending_confirmation=None,
        coverage=None,
        last_tool_result=None,
        session_id=session_id,
    )


__all__ = ["AgentMode", "AgentState", "Confirmation", "Coverage", "new_state"]

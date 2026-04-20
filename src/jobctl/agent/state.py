"""Typed agent state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from jobctl.llm.base import Message

AgentMode = Literal["chat", "ingest", "curate", "apply", "graph_qa"]
WorkflowKind = Literal["resume_ingest", "github_ingest", "apply"]


class Confirmation(TypedDict):
    question: str
    confirm_id: str


class Coverage(TypedDict, total=False):
    nodes_by_type: dict[str, int]
    orphans: list[dict[str, Any]]
    suggestions: list[str]
    total_nodes: int
    total_edges: int


class WorkflowRequest(TypedDict):
    kind: WorkflowKind
    payload: dict[str, Any]


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


def make_workflow_request(
    kind: WorkflowKind,
    payload: dict[str, Any] | None = None,
) -> WorkflowRequest:
    """Build a serializable workflow-start request for agent routing."""
    return WorkflowRequest(kind=kind, payload=dict(payload or {}))


def workflow_request_from_state(state: AgentState) -> WorkflowRequest | None:
    """Return the structured workflow request stored in ``last_tool_result``."""
    payload = state.get("last_tool_result") or {}
    candidate = payload.get("workflow_request") if isinstance(payload, dict) else None
    if candidate is None and isinstance(payload, dict) and "kind" in payload:
        candidate = payload
    if not isinstance(candidate, dict):
        return None
    kind = candidate.get("kind")
    if kind not in ("resume_ingest", "github_ingest", "apply"):
        return None
    request_payload = candidate.get("payload")
    if not isinstance(request_payload, dict):
        request_payload = {}
    return WorkflowRequest(kind=kind, payload=request_payload)


def store_workflow_request(state: AgentState, request: WorkflowRequest) -> AgentState:
    """Persist a workflow request in the agent state transport slot."""
    state["last_tool_result"] = {"workflow_request": request}
    return state


__all__ = [
    "AgentMode",
    "AgentState",
    "Confirmation",
    "Coverage",
    "WorkflowKind",
    "WorkflowRequest",
    "make_workflow_request",
    "new_state",
    "store_workflow_request",
    "workflow_request_from_state",
]

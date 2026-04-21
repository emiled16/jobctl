"""Typed agent state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from jobctl.llm.base import Message

AgentMode = Literal["chat", "ingest", "curate", "apply", "graph_qa", "refinement"]
WorkflowKind = Literal["resume_ingest", "github_ingest", "apply", "resume_refinement"]


class Confirmation(TypedDict, total=False):
    question: str
    confirm_id: str
    payload: dict[str, Any]


class Coverage(TypedDict, total=False):
    nodes_by_type: dict[str, int]
    orphans: list[dict[str, Any]]
    suggestions: list[str]
    total_nodes: int
    total_edges: int


class WorkflowRequest(TypedDict):
    kind: WorkflowKind
    payload: dict[str, Any]


class RefinementSession(TypedDict, total=False):
    pending_question_ids: list[str]
    current_index: int
    source_ref: str
    started_from: Literal["ingestion", "resume"]
    pending_update_plan: dict[str, Any]
    pending_answer: str


class AgentState(TypedDict, total=False):
    messages: list[Message]
    mode: AgentMode
    pending_confirmation: Confirmation | None
    coverage: Coverage | None
    last_tool_result: dict[str, Any] | None
    session_id: str
    refinement_session: RefinementSession | None


def new_state(session_id: str) -> AgentState:
    """Build an empty ``AgentState`` seeded with the session id."""
    return AgentState(
        messages=[],
        mode="chat",
        pending_confirmation=None,
        coverage=None,
        last_tool_result=None,
        session_id=session_id,
        refinement_session=None,
    )


def start_refinement_session(
    state: AgentState,
    question_ids: list[str],
    *,
    source_ref: str = "",
    started_from: Literal["ingestion", "resume"] = "resume",
) -> AgentState:
    state["refinement_session"] = {
        "pending_question_ids": list(question_ids),
        "current_index": 0,
        "source_ref": source_ref,
        "started_from": started_from,
    }
    state["mode"] = "refinement"
    return state


def advance_refinement_session(state: AgentState) -> AgentState:
    session = state.get("refinement_session")
    if not session:
        return state
    session["current_index"] = int(session.get("current_index") or 0) + 1
    session.pop("pending_update_plan", None)
    session.pop("pending_answer", None)
    if session["current_index"] >= len(session.get("pending_question_ids") or []):
        return clear_refinement_session(state)
    state["refinement_session"] = session
    state["mode"] = "refinement"
    return state


def clear_refinement_session(state: AgentState) -> AgentState:
    state["refinement_session"] = None
    state["mode"] = "chat"
    return state


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
    if kind not in ("resume_ingest", "github_ingest", "apply", "resume_refinement"):
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
    "RefinementSession",
    "WorkflowKind",
    "WorkflowRequest",
    "make_workflow_request",
    "new_state",
    "advance_refinement_session",
    "clear_refinement_session",
    "start_refinement_session",
    "store_workflow_request",
    "workflow_request_from_state",
]

"""Deterministic LangGraph router.

``route`` is the conditional edge function used by the LangGraph compiled
graph to pick the next node. The rules are intentionally free of LLM calls
so that navigation commands never burn tokens and can be exercised in unit
tests without any network access.
"""

from __future__ import annotations

from jobctl.agent.state import AgentState, workflow_request_from_state


_SLASH_TO_NODE = {
    "/ingest": "ingest_node",
    "/curate": "curate_node",
    "/apply": "apply_node",
    "/refine resume": "refinement_node",
}


def _last_user_message(state: AgentState) -> str:
    messages = state.get("messages") or []
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def route(state: AgentState) -> str:
    """Return the name of the next node LangGraph should execute."""
    if state.get("pending_confirmation"):
        return "wait_for_confirmation"

    workflow_request = workflow_request_from_state(state)
    if workflow_request is not None:
        if workflow_request["kind"] in ("resume_ingest", "github_ingest"):
            return "ingest_node"
        if workflow_request["kind"] == "apply":
            return "apply_node"
        if workflow_request["kind"] == "resume_refinement":
            return "refinement_node"

    if state.get("refinement_session"):
        return "refinement_node"

    last_user = _last_user_message(state).strip()
    lowered = last_user.lower()
    for prefix, node in _SLASH_TO_NODE.items():
        if lowered.startswith(prefix):
            return node

    mode = state.get("mode", "chat")
    if mode and mode != "chat":
        return f"{mode}_node"
    return "chat_node"


__all__ = ["route"]

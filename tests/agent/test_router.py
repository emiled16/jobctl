"""Unit tests for the deterministic agent router."""

from __future__ import annotations

import pytest

from jobctl.agent.router import route
from jobctl.agent.state import (
    AgentState,
    Confirmation,
    WorkflowKind,
    make_workflow_request,
    new_state,
    store_workflow_request,
)


def _state_with_messages(*messages, **overrides) -> AgentState:
    state = new_state(session_id="test")
    state["messages"] = [{"role": role, "content": content} for role, content in messages]
    for key, value in overrides.items():
        state[key] = value  # type: ignore[typeddict-unknown-key]
    return state


def test_pending_confirmation_routes_to_wait_node() -> None:
    state = _state_with_messages(
        ("user", "anything"),
        pending_confirmation=Confirmation(question="switch?", confirm_id="abc"),
    )

    assert route(state) == "wait_for_confirmation"


@pytest.mark.parametrize(
    "message,expected",
    [
        ("/ingest resume", "ingest_node"),
        ("/INGEST github", "ingest_node"),
        ("/curate duplicates", "curate_node"),
        ("/apply https://example.com", "apply_node"),
    ],
)
def test_slash_commands_route_to_matching_node(message: str, expected: str) -> None:
    state = _state_with_messages(("user", message))

    assert route(state) == expected


def test_mode_override_routes_to_mode_node() -> None:
    state = _state_with_messages(("user", "hello"))
    state["mode"] = "curate"

    assert route(state) == "curate_node"


def test_chat_mode_without_slash_routes_to_chat_node() -> None:
    state = _state_with_messages(("user", "what did I work on last year?"))

    assert route(state) == "chat_node"


def test_empty_history_defaults_to_chat_node() -> None:
    state = new_state(session_id="test")

    assert route(state) == "chat_node"


def test_slash_beats_mode_override() -> None:
    state = _state_with_messages(("user", "/ingest resume"))
    state["mode"] = "curate"

    assert route(state) == "ingest_node"


def test_pending_confirmation_beats_slash_command() -> None:
    state = _state_with_messages(
        ("user", "/ingest resume"),
        pending_confirmation=Confirmation(question="switch?", confirm_id="abc"),
    )

    assert route(state) == "wait_for_confirmation"


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("resume_ingest", "ingest_node"),
        ("github_ingest", "ingest_node"),
        ("apply", "apply_node"),
    ],
)
def test_workflow_requests_route_without_slash_text(
    kind: WorkflowKind,
    expected: str,
) -> None:
    state = _state_with_messages(("user", "start the workflow"))
    store_workflow_request(
        state,
        make_workflow_request(kind, {"url_or_text": "https://example.com/job"}),
    )

    assert route(state) == expected

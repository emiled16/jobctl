"""Tests for agent confirmation handling."""

from __future__ import annotations

import pytest

from jobctl.agent.nodes.confirm_node import wait_for_confirmation_node
from jobctl.agent.state import new_state
from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)


@pytest.mark.anyio
async def test_confirmation_accepts_pending_mode_payload() -> None:
    bus = AsyncEventBus()
    state = new_state("test")
    state["pending_confirmation"] = {
        "question": "Switch agent mode to `graph_qa`?",
        "confirm_id": "confirm-1",
        "kind": "mode_change",
        "payload": {"mode": "graph_qa"},
    }

    async def resolver(request: ConfirmationRequestedEvent) -> ConfirmationAnsweredEvent:
        assert request.kind == "mode_change"
        assert request.payload == {"mode": "graph_qa"}
        return ConfirmationAnsweredEvent(
            confirm_id=request.confirm_id,
            answer=True,
            payload=dict(request.payload),
        )

    result = await wait_for_confirmation_node(state, bus=bus, resolver=resolver)

    assert result["pending_confirmation"] is None
    assert result["mode"] == "graph_qa"


@pytest.mark.anyio
async def test_confirmation_decline_clears_pending_without_mode_change() -> None:
    bus = AsyncEventBus()
    state = new_state("test")
    state["pending_confirmation"] = {
        "question": "Switch agent mode to `curate`?",
        "confirm_id": "confirm-2",
        "kind": "mode_change",
        "payload": {"mode": "curate"},
    }

    async def resolver(request: ConfirmationRequestedEvent) -> ConfirmationAnsweredEvent:
        return ConfirmationAnsweredEvent(confirm_id=request.confirm_id, answer=False)

    result = await wait_for_confirmation_node(state, bus=bus, resolver=resolver)

    assert result["pending_confirmation"] is None
    assert result["mode"] == "chat"

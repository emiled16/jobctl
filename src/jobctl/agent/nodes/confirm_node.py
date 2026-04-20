"""Node that pauses LangGraph execution while awaiting user confirmation."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from jobctl.agent.state import AgentState
from jobctl.core.events import (
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
    AsyncEventBus,
    JobctlEvent,
)

logger = logging.getLogger(__name__)

ConfirmationResolver = Callable[[ConfirmationRequestedEvent], Awaitable[ConfirmationAnsweredEvent]]


async def _default_resolver(
    request: ConfirmationRequestedEvent,
    bus: AsyncEventBus,
    timeout: float | None,
) -> ConfirmationAnsweredEvent:
    queue = bus.subscribe()
    try:
        while True:
            event: JobctlEvent = (
                await asyncio.wait_for(queue.get(), timeout)
                if timeout is not None
                else await queue.get()
            )
            if (
                isinstance(event, ConfirmationAnsweredEvent)
                and event.confirm_id == request.confirm_id
            ):
                return event
    finally:
        bus.unsubscribe(queue)


async def wait_for_confirmation_node(
    state: AgentState,
    *,
    bus: AsyncEventBus,
    resolver: ConfirmationResolver | None = None,
    timeout: float | None = None,
) -> AgentState:
    """Await ``ConfirmationAnsweredEvent`` matching the pending request.

    If the user answers ``True``, the ``mode`` is taken from the pending
    confirmation's ``payload`` (when present) and ``pending_confirmation``
    is cleared. A ``False`` answer simply clears the confirmation so the
    router re-enters ``chat_node``.
    """
    pending = state.get("pending_confirmation")
    if pending is None:
        return state

    request = ConfirmationRequestedEvent(
        question=pending["question"],
        confirm_id=pending["confirm_id"],
        kind=str(pending.get("kind") or "yes_no"),
        payload=dict(pending.get("payload") or {}),
    )
    bus.publish(request)

    if resolver is None:
        answer = await _default_resolver(request, bus, timeout)
    else:
        answer = await resolver(request)

    state["pending_confirmation"] = None
    if answer.answer:
        mode = answer.payload.get("mode") if answer.payload else pending.get("payload", {}).get("mode")
        if mode:
            state["mode"] = mode  # type: ignore[typeddict-item]
    return state


__all__ = ["ConfirmationResolver", "wait_for_confirmation_node"]

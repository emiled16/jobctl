"""The default ``chat_node`` — streams an LLM response to the event bus."""

from __future__ import annotations

import logging

from jobctl.agent.prompts import SYSTEM_PROMPTS
from jobctl.agent.state import AgentState
from jobctl.core.events import (
    AgentDoneEvent,
    AgentTokenEvent,
    AsyncEventBus,
)
from jobctl.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


def _prepare_messages(state: AgentState) -> list[Message]:
    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPTS["chat"]),
    ]
    for message in state.get("messages") or []:
        role = message.get("role")
        content = message.get("content")
        if role is None or content is None:
            continue
        messages.append(Message(role=role, content=content))
    return messages


def chat_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    bus: AsyncEventBus,
) -> AgentState:
    """Stream a chat turn through ``provider`` and append to ``state``.

    The node publishes :class:`AgentTokenEvent` for each streamed chunk and
    :class:`AgentDoneEvent` once the full answer is assembled. It returns
    the updated :class:`AgentState` with the assistant turn appended.
    """
    messages = _prepare_messages(state)
    buffer: list[str] = []
    try:
        for chunk in provider.stream(messages):
            delta = chunk.get("delta") or ""
            if delta:
                buffer.append(delta)
                bus.publish(AgentTokenEvent(token=delta))
            if chunk.get("done"):
                break
    except Exception as exc:  # noqa: BLE001 - surfaced to the bus below
        logger.exception("chat_node provider.stream failed")
        fallback = f"Sorry, the LLM call failed: {exc}"
        bus.publish(AgentDoneEvent(role="assistant", content=fallback))
        state_messages = list(state.get("messages") or [])
        state_messages.append(Message(role="assistant", content=fallback))
        state["messages"] = state_messages
        return state

    reply = "".join(buffer).strip()
    bus.publish(AgentDoneEvent(role="assistant", content=reply))

    state_messages = list(state.get("messages") or [])
    state_messages.append(Message(role="assistant", content=reply))
    state["messages"] = state_messages
    return state


__all__ = ["chat_node"]

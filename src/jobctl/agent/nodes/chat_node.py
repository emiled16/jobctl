"""The default ``chat_node`` — streams an LLM response to the event bus."""

from __future__ import annotations

import logging
import uuid

from jobctl.agent.prompts import SYSTEM_PROMPTS
from jobctl.agent.state import AgentState
from jobctl.core.events import (
    AgentDoneEvent,
    AgentTokenEvent,
    AsyncEventBus,
    ConfirmationRequestedEvent,
)
from jobctl.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


_RESUME_KEYWORDS = ("resume", " cv ", "curriculum vitae")
_GITHUB_KEYWORDS = ("github", "repositories", "repos")


def _last_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages") or []):
        if message.get("role") == "user":
            return (message.get("content") or "").lower()
    return ""


def _maybe_suggest_ingestion(state: AgentState, bus: AsyncEventBus) -> None:
    """Publish an inline ConfirmationRequestedEvent when the user's last
    message hints at a resume or GitHub repo ingestion opportunity.

    Only fires when the agent is in ``chat`` mode. The suggestion is a soft
    cue rendered as an inline confirm card in :class:`ChatView`.
    """

    if state.get("mode", "chat") != "chat":
        return
    text = _last_user_text(state)
    if not text:
        return
    # Don't nag if we've already proposed recently in this turn.
    if state.get("pending_confirmation"):
        return

    if any(kw in text for kw in _RESUME_KEYWORDS):
        bus.publish(
            ConfirmationRequestedEvent(
                question="Want me to ingest a resume file?",
                confirm_id=uuid.uuid4().hex,
                kind="file_pick_resume",
            )
        )
        return
    if any(kw in text for kw in _GITHUB_KEYWORDS):
        bus.publish(
            ConfirmationRequestedEvent(
                question="Want me to ingest your GitHub repos?",
                confirm_id=uuid.uuid4().hex,
                kind="github_user",
            )
        )


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

    try:
        _maybe_suggest_ingestion(state, bus)
    except Exception:  # noqa: BLE001 - best-effort suggestion only
        logger.exception("chat_node proactive suggestion failed")

    return state


__all__ = ["chat_node"]

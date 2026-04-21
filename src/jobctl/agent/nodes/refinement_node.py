"""Agent node for one-question-at-a-time resume refinement."""

from __future__ import annotations

import sqlite3
from typing import Any

from jobctl.agent.state import (
    AgentState,
    advance_refinement_session,
    clear_refinement_session,
    start_refinement_session,
    workflow_request_from_state,
)
from jobctl.core.events import AgentDoneEvent, AsyncEventBus
from jobctl.ingestion.enrichment import (
    apply_graph_update_plan,
    build_graph_update_from_answer,
    preview_graph_update_plan,
)
from jobctl.ingestion.questions import RefinementQuestionStore
from jobctl.ingestion.schemas import GraphUpdatePlan
from jobctl.llm.base import LLMProvider, Message


def refinement_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    bus: AsyncEventBus,
) -> AgentState:
    store = RefinementQuestionStore(conn)
    workflow_request = workflow_request_from_state(state)
    if workflow_request and workflow_request["kind"] == "resume_refinement":
        pending = store.list_pending(
            source_ref=workflow_request["payload"].get("source_ref"),
            limit=10,
        )
        state["last_tool_result"] = None
        if not pending:
            return _assistant(state, bus, "There are no pending resume refinement questions.")
        state = start_refinement_session(
            state,
            [str(question.id) for question in pending if question.id],
            source_ref=workflow_request["payload"].get("source_ref") or "",
            started_from="resume",
        )

    session = state.get("refinement_session")
    if not session:
        pending = store.list_pending(limit=10)
        if not pending:
            return _assistant(state, bus, "There are no pending resume refinement questions.")
        state = start_refinement_session(
            state,
            [str(question.id) for question in pending if question.id],
            source_ref=pending[0].source_ref,
            started_from="resume",
        )
        session = state.get("refinement_session")

    assert session is not None
    pending_plan = session.get("pending_update_plan")
    if pending_plan:
        return _handle_pending_update_review(
            state,
            provider=provider,
            conn=conn,
            bus=bus,
            store=store,
        )

    question_ids = session.get("pending_question_ids") or []
    index = int(session.get("current_index") or 0)
    if index >= len(question_ids):
        return _assistant(clear_refinement_session(state), bus, "Resume refinement is complete.")

    question = store.get(question_ids[index])
    if question is None:
        return refinement_node(
            advance_refinement_session(state), provider=provider, conn=conn, bus=bus
        )

    answer = _last_user_message(state).strip()
    if _is_command(answer):
        return _assistant(state, bus, _render_question(index, len(question_ids), question))
    lowered = answer.casefold()
    if lowered in {"later", "stop"}:
        return _assistant(
            clear_refinement_session(state),
            bus,
            "Paused resume refinement. Use `/refine resume` to continue later.",
        )
    if lowered == "skip":
        if question.id:
            store.mark_skipped(question.id)
        return _assistant(
            advance_refinement_session(state),
            bus,
            "Skipped that question.",
        )

    if answer:
        shim = _ProviderShim(provider)
        plan = build_graph_update_from_answer(question, answer, shim)
        session["pending_update_plan"] = plan.model_dump()
        session["pending_answer"] = answer
        state["refinement_session"] = session
        preview = preview_graph_update_plan(conn, plan)
        return _assistant(
            state,
            bus,
            (
                "Review the proposed graph update:\n\n"
                f"{preview}\n\n"
                "Reply `accept` to apply this change, or `reject` to discard it."
            ),
        )

    return _assistant(state, bus, _render_question(index, len(question_ids), question))


def _handle_pending_update_review(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    bus: AsyncEventBus,
    store: RefinementQuestionStore,
) -> AgentState:
    session = state.get("refinement_session") or {}
    answer = _last_user_message(state).strip().casefold()
    if answer not in {"accept", "yes", "y", "reject", "no", "n"}:
        plan = GraphUpdatePlan.model_validate(session["pending_update_plan"])
        preview = preview_graph_update_plan(conn, plan)
        return _assistant(
            state,
            bus,
            (f"Please reply `accept` or `reject` for this proposed graph update:\n\n{preview}"),
        )

    question_ids = session.get("pending_question_ids") or []
    index = int(session.get("current_index") or 0)
    question_id = question_ids[index] if index < len(question_ids) else None
    if answer in {"accept", "yes", "y"}:
        plan = GraphUpdatePlan.model_validate(session["pending_update_plan"])
        shim = _ProviderShim(provider)
        apply_graph_update_plan(
            conn, plan, shim, plan.source_ref or session.get("source_ref") or ""
        )
        if question_id:
            pending_answer = str(session.get("pending_answer") or "")
            store.mark_answered(question_id, pending_answer)
            store.mark_converted_to_update(question_id)
        next_state = advance_refinement_session(state)
        return _render_next_question_or_complete(next_state, bus, store)

    if question_id:
        store.mark_skipped(question_id)
    next_state = advance_refinement_session(state)
    return _render_next_question_or_complete(next_state, bus, store)


def _render_next_question_or_complete(
    state: AgentState,
    bus: AsyncEventBus,
    store: RefinementQuestionStore,
) -> AgentState:
    session = state.get("refinement_session")
    if not session:
        return _assistant(state, bus, "Resume refinement is complete.")
    question_ids = session.get("pending_question_ids") or []
    index = int(session.get("current_index") or 0)
    if index >= len(question_ids):
        return _assistant(clear_refinement_session(state), bus, "Resume refinement is complete.")
    question = store.get(question_ids[index])
    if question is None:
        return _assistant(state, bus, "Resume refinement is complete.")
    return _assistant(state, bus, _render_question(index, len(question_ids), question))


def _render_question(index: int, total: int, question: Any) -> str:
    options = ""
    if question.options:
        options = "\n" + "\n".join(f"- {option}" for option in question.options)
    free_text = " You can answer in your own words." if question.allow_free_text else ""
    return (
        f"Question {index + 1} of {total}: {question.prompt}"
        f"{options}\n\nReply with an answer, `skip`, or `later`.{free_text}"
    )


def _assistant(state: AgentState, bus: AsyncEventBus, text: str) -> AgentState:
    messages = list(state.get("messages") or [])
    messages.append(Message(role="assistant", content=text))
    state["messages"] = messages
    bus.publish(AgentDoneEvent(role="assistant", content=text))
    return state


def _last_user_message(state: AgentState) -> str:
    messages = state.get("messages") or []
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _is_command(message: str) -> bool:
    return message.casefold().startswith("/refine resume") or message.casefold().startswith(
        "continue resume refinement"
    )


class _ProviderShim:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def chat_structured(self, messages: list[dict[str, Any]], response_format: type) -> Any:
        import json

        response = self._provider.chat(messages)
        content = response.get("content") or "{}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {}
        return response_format.model_validate(payload)

    def get_embedding(self, text: str) -> list[float]:
        return self._provider.embed([text])[0]


__all__ = ["refinement_node"]

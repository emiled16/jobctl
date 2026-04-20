"""Agent node that launches background apply (JD-evaluate + generate) jobs."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from jobctl.agent.state import AgentState, workflow_request_from_state
from jobctl.config import JobctlConfig
from jobctl.core.events import AgentDoneEvent, AsyncEventBus
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.db.connection import get_connection
from jobctl.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


_URL_PATTERN = re.compile(r"https?://\S+")


def _append_assistant(state: AgentState, text: str, bus: AsyncEventBus) -> AgentState:
    messages = list(state.get("messages") or [])
    messages.append(Message(role="assistant", content=text))
    state["messages"] = messages
    bus.publish(AgentDoneEvent(role="assistant", content=text))
    return state


def _last_user(state: AgentState) -> str:
    for message in reversed(state.get("messages") or []):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _extract_url_or_text(state: AgentState) -> str | None:
    workflow_request = workflow_request_from_state(state)
    if workflow_request is not None and workflow_request["kind"] == "apply":
        request_payload = workflow_request["payload"]
        value = (
            request_payload.get("url_or_text")
            or request_payload.get("jd_url")
            or request_payload.get("jd_text")
        )
        return str(value) if value else None

    payload = state.get("last_tool_result") or {}
    if payload.get("url_or_text"):
        return str(payload["url_or_text"])
    if payload.get("jd_url"):
        return str(payload["jd_url"])

    text = _last_user(state)
    if not text:
        return None
    match = _URL_PATTERN.search(text)
    if match:
        return match.group(0)
    # Treat the remainder as a pasted JD, stripping the slash prefix.
    stripped = text
    if stripped.startswith("/apply"):
        stripped = stripped[len("/apply") :].strip()
    return stripped or None


def _build_shim(provider: LLMProvider) -> Any:
    import json as _json

    class _Shim:
        def chat(self, messages, **kwargs):
            return provider.chat(messages, **kwargs)

        def chat_structured(self, messages, response_format):
            response = provider.chat(messages)
            content = response.get("content") or "{}"
            try:
                payload = _json.loads(content)
            except _json.JSONDecodeError:
                payload = {}
            return response_format.model_validate(payload)

        def get_embedding(self, text: str) -> list[float]:
            return provider.embed([text])[0]

        def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
            return provider.embed(texts)

    return _Shim()


def start_apply(
    *,
    conn: sqlite3.Connection,
    provider: LLMProvider,
    bus: AsyncEventBus,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    config: JobctlConfig,
    url_or_text: str,
    db_path: Path | None = None,
) -> str:
    """Run ``run_apply`` in the background. Returns the job id."""
    job_id = store.create_job(
        source_type="apply",
        source_key=url_or_text[:200],
        cursor={"url_or_text": url_or_text},
    )

    def _do_apply() -> dict[str, Any]:
        from jobctl.jobs.apply_pipeline import run_apply

        worker_conn = conn
        if db_path is not None:
            worker_conn = get_connection(db_path)

        try:
            shim = _build_shim(provider)
            app_id = run_apply(worker_conn, url_or_text, shim, config, bus=bus, job_id=job_id)
            return {"app_id": app_id}
        finally:
            if db_path is not None:
                worker_conn.close()

    runner.submit(job_id, _do_apply, source="apply")
    return job_id


def apply_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    config: JobctlConfig,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    bus: AsyncEventBus,
    db_path: Path | None = None,
) -> AgentState:
    """Launch a background apply flow based on the user's request."""

    url_or_text = _extract_url_or_text(state)
    if not url_or_text:
        return _append_assistant(
            state,
            "I need a job posting URL or JD text before I can evaluate fit.",
            bus,
        )

    try:
        job_id = start_apply(
            conn=conn,
            provider=provider,
            bus=bus,
            store=store,
            runner=runner,
            config=config,
            url_or_text=url_or_text,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("apply_node failed to start background job")
        return _append_assistant(state, f"Sorry, apply failed to start: {exc}", bus)

    state["last_tool_result"] = None
    return _append_assistant(
        state,
        f"Started apply flow (job `{job_id}`). Progress updates will stream here.",
        bus,
    )


__all__ = ["apply_node", "start_apply"]

"""Agent node that launches background ingestion jobs."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from jobctl.agent.state import AgentState, workflow_request_from_state
from jobctl.core.events import AgentDoneEvent, AsyncEventBus, IngestDoneEvent
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.db.connection import get_connection
from jobctl.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


def _append_assistant(state: AgentState, text: str, bus: AsyncEventBus) -> AgentState:
    messages = list(state.get("messages") or [])
    messages.append(Message(role="assistant", content=text))
    state["messages"] = messages
    bus.publish(AgentDoneEvent(role="assistant", content=text))
    return state


def start_resume_ingest(
    *,
    conn: sqlite3.Connection,
    provider: LLMProvider,
    bus: AsyncEventBus,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    resume_path: Path,
    db_path: Path | None = None,
) -> str:
    """Kick off a resume ingest in the background; return the job id."""
    job_id = store.create_job(
        source_type="resume",
        source_key=str(resume_path),
        cursor={"path": str(resume_path)},
    )

    def _do_ingest() -> dict[str, Any]:
        from jobctl.ingestion.resume import (
            extract_facts_from_resume,
            persist_facts,
            read_resume,
        )

        worker_conn = conn
        worker_store = store
        if db_path is not None:
            worker_conn = get_connection(db_path)
            worker_store = BackgroundJobStore(worker_conn)

        try:
            text = read_resume(resume_path)

            class _Shim:
                def chat_structured(self, messages, response_format):
                    response = provider.chat(messages)
                    import json

                    content = response.get("content") or "{}"
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError:
                        payload = {"facts": []}
                    return response_format.model_validate(payload)

                def get_embedding(self, text):
                    return provider.embed([text])[0]

            shim = _Shim()
            profile = extract_facts_from_resume(text, shim)
            added = persist_facts(
                worker_conn,
                profile.facts,
                shim,
                interactive=False,
                bus=bus,
                store=worker_store,
                job_id=job_id,
            )
            bus.publish(IngestDoneEvent(source="resume", facts_added=added, job_id=job_id))
            return {"facts_added": added}
        finally:
            if db_path is not None:
                worker_conn.close()

    runner.submit(job_id, _do_ingest, source="resume", label=f"Resume ingest: {resume_path.name}")
    return job_id


def start_github_ingest(
    *,
    conn: sqlite3.Connection,
    provider: LLMProvider,
    bus: AsyncEventBus,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    username_or_urls: list[str],
    preselected_repos: list[tuple[str, str]] | None = None,
    db_path: Path | None = None,
) -> str:
    job_id = store.create_job(
        source_type="github",
        source_key=",".join(username_or_urls) or "github",
        cursor={
            "usernames": username_or_urls,
            "preselected": preselected_repos,
        },
    )

    def _do_ingest() -> dict[str, Any]:
        from jobctl.ingestion.github import ingest_github

        worker_conn = conn
        worker_store = store
        if db_path is not None:
            worker_conn = get_connection(db_path)
            worker_store = BackgroundJobStore(worker_conn)

        try:

            class _Shim:
                def chat_structured(self, messages, response_format):
                    import json

                    response = provider.chat(messages)
                    content = response.get("content") or "{}"
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError:
                        payload = {"facts": []}
                    return response_format.model_validate(payload)

                def get_embedding(self, text):
                    return provider.embed([text])[0]

            added = ingest_github(
                worker_conn,
                username_or_urls,
                _Shim(),
                interactive=False,
                bus=bus,
                store=worker_store,
                job_id=job_id,
                preselected_repos=preselected_repos,
            )
            return {"facts_added": added}
        finally:
            if db_path is not None:
                worker_conn.close()

    runner.submit(job_id, _do_ingest, source="github", label="GitHub ingest")
    return job_id


def ingest_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    bus: AsyncEventBus,
    db_path: Path | None = None,
) -> AgentState:
    """Route ingest requests from ``state.last_tool_result`` into background jobs."""
    payload = state.get("last_tool_result") or {}
    source_type = str(payload.get("source_type") or "").lower()
    source_value = payload.get("source_value")
    workflow_request = workflow_request_from_state(state)
    if workflow_request is not None:
        request_payload = workflow_request["payload"]
        if workflow_request["kind"] == "resume_ingest":
            source_type = "resume"
            source_value = (
                request_payload.get("path")
                or request_payload.get("resume_path")
                or request_payload.get("source_value")
            )
        elif workflow_request["kind"] == "github_ingest":
            source_type = "github"
            source_value = (
                request_payload.get("username_or_urls")
                or request_payload.get("usernames")
                or request_payload.get("urls")
                or request_payload.get("source_value")
            )

    if source_type == "resume":
        path = Path(str(source_value)).expanduser() if source_value else None
        if path is None or not path.exists():
            return _append_assistant(
                state,
                "I need a resume file path before I can start ingesting.",
                bus,
            )
        job_id = start_resume_ingest(
            conn=conn,
            provider=provider,
            bus=bus,
            store=store,
            runner=runner,
            resume_path=path,
            db_path=db_path,
        )
        state["last_tool_result"] = None
        return _append_assistant(
            state,
            f"Started resume ingestion (job `{job_id}`). I'll report progress here.",
            bus,
        )

    if source_type == "github":
        usernames = source_value if isinstance(source_value, list) else [source_value]
        usernames = [str(u) for u in usernames if u]
        if not usernames:
            return _append_assistant(
                state,
                "I need a GitHub username, profile URL, or repo URL before I can start ingesting.",
                bus,
            )
        preselected = (
            workflow_request["payload"].get("preselected_repos")
            if workflow_request is not None
            else payload.get("preselected_repos")
        )
        job_id = start_github_ingest(
            conn=conn,
            provider=provider,
            bus=bus,
            store=store,
            runner=runner,
            username_or_urls=usernames,
            preselected_repos=preselected,
            db_path=db_path,
        )
        state["last_tool_result"] = None
        return _append_assistant(
            state,
            f"Started GitHub ingestion for {', '.join(usernames)} (job `{job_id}`).",
            bus,
        )

    return _append_assistant(
        state,
        "I can ingest either a resume file or GitHub repos. Which would you like?",
        bus,
    )


__all__ = ["ingest_node", "start_github_ingest", "start_resume_ingest"]

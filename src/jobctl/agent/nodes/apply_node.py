"""Agent node that launches background apply (JD-evaluate + generate) jobs."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jobctl.agent.state import AgentState, workflow_request_from_state
from jobctl.config import JobctlConfig
from jobctl.core.events import AgentDoneEvent, AsyncEventBus
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.db.connection import get_connection
from jobctl.llm.base import LLMProvider, Message
from jobctl.rag.factory import create_vector_store
from jobctl.rag.store import VectorStore

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
    """Adapt an ``LLMProvider`` to the ``chat_structured`` interface used by the Apply pipeline.

    We prefer the provider's native ``chat_structured`` (e.g. OpenAI
    structured outputs via ``response_format=...``) because it reliably returns
    complete JSON matching the schema. If the provider refuses the schema
    (e.g. OpenAI strict-mode rejects optional fields or open-ended dicts
    like ``ResumeYAML``), we fall back to asking the model for plain JSON
    and validating with Pydantic.
    """
    import json as _json

    def _invalid_payload(response_format: type, exc: Exception) -> ValueError:
        return ValueError(
            f"Could not extract a valid {response_format.__name__}. "
            "If this was a gated job page, paste the full job description text instead. "
            f"Validation error: {exc}"
        )

    def _json_fallback(messages, response_format):
        schema_hint = _json.dumps(response_format.model_json_schema(), sort_keys=True)
        hinted_messages = list(messages) + [
            {
                "role": "system",
                "content": (
                    "Respond with a single JSON object that conforms to this JSON schema. "
                    "Do not include any prose, code fences, or commentary. "
                    "Use empty strings or empty arrays when a value is unknown.\n"
                    f"{schema_hint}"
                ),
            }
        ]
        response = provider.chat(hinted_messages)
        content = (response.get("content") or "").strip()
        content = _strip_code_fence(content)
        try:
            payload = _json.loads(content) if content else {}
        except _json.JSONDecodeError:
            payload = {}
        try:
            return response_format.model_validate(payload)
        except ValidationError as exc:
            raise _invalid_payload(response_format, exc) from exc

    class _Shim:
        def chat(self, messages, **kwargs):
            return provider.chat(messages, **kwargs)

        def chat_structured(self, messages, response_format):
            if hasattr(provider, "chat_structured"):
                try:
                    return provider.chat_structured(  # type: ignore[attr-defined]
                        list(messages), response_format=response_format
                    )
                except ValidationError as exc:
                    raise _invalid_payload(response_format, exc) from exc
                except Exception as exc:  # noqa: BLE001
                    # Provider refused the schema (e.g. OpenAI strict mode
                    # rejects optional fields or open-ended dicts). Fall back
                    # to plain chat + JSON parsing so complex generation
                    # schemas like ResumeYAML still work.
                    logger.warning(
                        "Structured output failed for %s; falling back to JSON chat. Reason: %s",
                        response_format.__name__,
                        exc,
                    )
                    return _json_fallback(messages, response_format)

            return _json_fallback(messages, response_format)

        def get_embedding(self, text: str) -> list[float]:
            return provider.embed([text])[0]

        def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
            return provider.embed(texts)

    return _Shim()


def _strip_code_fence(content: str) -> str:
    """Remove a leading ```json / ``` fence and trailing ``` if present."""
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) < 2:
        return content
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def start_apply(
    *,
    conn: sqlite3.Connection,
    provider: LLMProvider,
    bus: AsyncEventBus,
    store: BackgroundJobStore,
    runner: BackgroundJobRunner,
    config: JobctlConfig,
    vector_store: VectorStore,
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
        worker_vector_store = vector_store
        if db_path is not None:
            worker_conn = get_connection(db_path)
            project_root = db_path.parent.parent
            worker_vector_store = create_vector_store(config, project_root)

        try:
            shim = _build_shim(provider)
            app_id = run_apply(
                worker_conn,
                url_or_text,
                shim,
                config,
                worker_vector_store,
                bus=bus,
                job_id=job_id,
            )
            return {"app_id": app_id}
        finally:
            if db_path is not None:
                worker_vector_store.close()
                worker_conn.close()

    runner.submit(job_id, _do_apply, source="apply", label="Apply workflow")
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
    vector_store: VectorStore | None = None,
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
        if vector_store is None:
            raise ValueError("Vector store is not configured")
        job_id = start_apply(
            conn=conn,
            provider=provider,
            bus=bus,
            store=store,
            runner=runner,
            config=config,
            vector_store=vector_store,
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

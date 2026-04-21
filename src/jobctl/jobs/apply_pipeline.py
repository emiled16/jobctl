"""End-to-end job application orchestration."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.prompt import Confirm

from jobctl.config import CONFIG_DIR_NAME, find_project_root
from jobctl.core.events import (
    ApplyProgressEvent,
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
    JobLifecycleEvent,
)
from jobctl.generation.cover_letter import (
    generate_cover_letter_yaml,
    save_and_review_cover_letter,
)
from jobctl.generation.renderer import output_pdf_path, render_pdf
from jobctl.generation.resume import generate_resume_yaml, save_and_review
from jobctl.jobs.evaluator import display_evaluation, evaluate_fit, retrieve_relevant_experience
from jobctl.jobs.fetcher import fetch_and_parse_jd
from jobctl.jobs.tracker import create_application, update_application, update_status
from jobctl.rag.store import VectorStore


console = Console()


ConfirmFn = Callable[[str, str], bool]


def _progress(
    bus: AsyncEventBus | None,
    step: str,
    message: str = "",
    *,
    job_id: str | None = None,
) -> None:
    if bus is None:
        console.print(f"[dim]{step}:[/dim] {message}")
        return
    bus.publish(ApplyProgressEvent(step=step, message=message, job_id=job_id))


def _bus_confirm(
    bus: AsyncEventBus,
    question: str,
    payload_kind: str,
    *,
    job_id: str | None = None,
    label: str = "Apply workflow",
) -> bool:
    confirm_id = uuid.uuid4().hex
    queue = bus.subscribe()
    try:
        if job_id is not None:
            bus.publish(
                JobLifecycleEvent(
                    job_id=job_id,
                    kind="apply",
                    label=label,
                    phase="waiting_for_user",
                    message=question,
                )
            )
        bus.publish(
            ConfirmationRequestedEvent(question=question, confirm_id=confirm_id, kind=payload_kind)
        )
        # Poll the subscriber queue synchronously, letting the loop run.
        while True:
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                import time

                time.sleep(0.05)
                continue
            if isinstance(event, ConfirmationAnsweredEvent) and event.confirm_id == confirm_id:
                if job_id is not None:
                    bus.publish(
                        JobLifecycleEvent(
                            job_id=job_id,
                            kind="apply",
                            label=label,
                            phase="running",
                            message="Resuming",
                        )
                    )
                return bool(event.answer)
    finally:
        bus.unsubscribe(queue)


async def _bus_confirm_async(bus: AsyncEventBus, question: str, payload_kind: str) -> bool:
    confirm_id = uuid.uuid4().hex
    queue = bus.subscribe()
    try:
        bus.publish(
            ConfirmationRequestedEvent(question=question, confirm_id=confirm_id, kind=payload_kind)
        )
        while True:
            event = await queue.get()
            if isinstance(event, ConfirmationAnsweredEvent) and event.confirm_id == confirm_id:
                return bool(event.answer)
    finally:
        bus.unsubscribe(queue)


def _confirm(
    bus: AsyncEventBus | None,
    confirm_fn: ConfirmFn | None,
    question: str,
    *,
    kind: str = "yes_no",
    default: bool = True,
    job_id: str | None = None,
) -> bool:
    if confirm_fn is not None:
        return confirm_fn(question, kind)
    if bus is not None:
        return _bus_confirm(bus, question, kind, job_id=job_id)
    return Confirm.ask(question, default=default)


def run_apply(
    conn: sqlite3.Connection,
    url_or_text: str,
    llm_client: Any,
    config: Any,
    vector_store: VectorStore,
    *,
    bus: AsyncEventBus | None = None,
    confirm_fn: ConfirmFn | None = None,
    job_id: str | None = None,
) -> str:
    """Run the full JD evaluation and material generation flow.

    When ``bus`` is provided, pipeline progress is published via
    :class:`ApplyProgressEvent` and user confirmations go through
    :class:`ConfirmationRequestedEvent` / :class:`ConfirmationAnsweredEvent`.
    If ``bus`` is ``None``, the legacy Rich-prompt flow is used, keeping the
    headless ``render --headless`` path working unchanged.
    """

    _progress(bus, "fetch_jd", f"Fetching JD from {url_or_text[:80]}", job_id=job_id)
    jd = fetch_and_parse_jd(url_or_text, llm_client)

    _progress(bus, "retrieve", "Retrieving relevant experience", job_id=job_id)
    relevant_experience = retrieve_relevant_experience(conn, jd, llm_client, vector_store)

    _progress(bus, "evaluate", "Evaluating fit", job_id=job_id)
    evaluation = evaluate_fit(jd, relevant_experience, llm_client)
    if bus is None:
        display_evaluation(jd, evaluation)

    app_id = create_application(
        conn,
        company=jd.company,
        role=jd.title,
        url=url_or_text if url_or_text.startswith(("http://", "https://")) else None,
        jd=jd,
        evaluation=evaluation,
    )
    _progress(bus, "application_created", f"app_id={app_id}", job_id=job_id)

    if not _confirm(bus, confirm_fn, "Generate tailored materials?", job_id=job_id):
        _progress(bus, "done", f"Tracker entry created: {app_id}", job_id=job_id)
        return app_id

    output_dir = _application_output_dir(jd)
    _progress(bus, "generate_resume", "Generating tailored resume YAML", job_id=job_id)
    resume_yaml_path = _generate_reviewed_resume(
        jd, relevant_experience, evaluation, llm_client, output_dir, bus=bus
    )

    _progress(bus, "render_resume_pdf", str(resume_yaml_path), job_id=job_id)
    resume_pdf_path = render_pdf(
        resume_yaml_path,
        getattr(config, "default_template", None),
        output_pdf_path(resume_yaml_path),
    )

    cover_letter_yaml_path: Path | None = None
    cover_letter_pdf_path: Path | None = None
    if _confirm(bus, confirm_fn, "Generate cover letter?", job_id=job_id):
        _progress(bus, "generate_cover_letter", "Generating cover letter YAML", job_id=job_id)
        cover_letter_yaml_path = _generate_reviewed_cover_letter(
            jd,
            relevant_experience,
            evaluation,
            llm_client,
            output_dir,
            bus=bus,
        )
        _progress(bus, "render_cover_letter_pdf", str(cover_letter_yaml_path), job_id=job_id)
        cover_letter_pdf_path = render_pdf(
            cover_letter_yaml_path,
            "cover-letter.html",
            output_pdf_path(cover_letter_yaml_path),
        )

    update_application(
        conn,
        app_id,
        resume_yaml_path=str(resume_yaml_path),
        resume_pdf_path=str(resume_pdf_path),
        cover_letter_yaml_path=str(cover_letter_yaml_path) if cover_letter_yaml_path else None,
        cover_letter_pdf_path=str(cover_letter_pdf_path) if cover_letter_pdf_path else None,
    )
    update_status(conn, app_id, "materials_ready")

    _progress(bus, "done", f"Materials ready for {app_id}", job_id=job_id)
    if bus is None:
        console.print(f"Tracker entry created: {app_id}")
        console.print(f"Resume YAML: {resume_yaml_path}")
        console.print(f"Resume PDF: {resume_pdf_path}")
        if cover_letter_yaml_path and cover_letter_pdf_path:
            console.print(f"Cover letter YAML: {cover_letter_yaml_path}")
            console.print(f"Cover letter PDF: {cover_letter_pdf_path}")
    return app_id


def _generate_reviewed_resume(
    jd,
    relevant_experience: dict,
    evaluation,
    llm_client: Any,
    output_dir: Path,
    *,
    bus: AsyncEventBus | None = None,
) -> Path:
    while True:
        resume = generate_resume_yaml(jd, relevant_experience, evaluation, llm_client)
        if bus is not None:
            # In TUI mode we don't gate on an interactive editor review.
            resume_yaml_path = save_and_review(resume, output_dir, interactive=False)
        else:
            resume_yaml_path = save_and_review(resume, output_dir)
        if resume_yaml_path is not None:
            return resume_yaml_path


def _generate_reviewed_cover_letter(
    jd,
    relevant_experience: dict,
    evaluation,
    llm_client: Any,
    output_dir: Path,
    *,
    bus: AsyncEventBus | None = None,
) -> Path:
    while True:
        cover_letter = generate_cover_letter_yaml(jd, relevant_experience, evaluation, llm_client)
        if bus is not None:
            cover_letter_yaml_path = save_and_review_cover_letter(
                cover_letter, output_dir, interactive=False
            )
        else:
            cover_letter_yaml_path = save_and_review_cover_letter(cover_letter, output_dir)
        if cover_letter_yaml_path is not None:
            return cover_letter_yaml_path


def _application_output_dir(jd) -> Path:
    project_root = find_project_root(Path.cwd())
    date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    company_slug = _slugify(jd.company or "company")
    role_slug = _slugify(jd.title or "role")
    return project_root / CONFIG_DIR_NAME / "exports" / f"{date_prefix}-{company_slug}-{role_slug}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "job"


__all__ = ["run_apply"]

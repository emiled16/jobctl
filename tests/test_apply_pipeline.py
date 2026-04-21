import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from jobctl.config import default_config, save_config
from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
    JobLifecycleEvent,
)
from jobctl.db.connection import get_connection
from jobctl.generation.schemas import CoverLetterYAML, ResumeYAML
from jobctl.jobs import apply_pipeline
from jobctl.jobs.tracker import get_application
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


def _next_event(queue, *, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not queue.empty():
            return queue.get_nowait()
        time.sleep(0.01)
    raise AssertionError("timed out waiting for event")


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".jobctl" / "exports").mkdir(parents=True)
    (project_root / ".jobctl" / "templates").mkdir()
    save_config(project_root, default_config())
    monkeypatch.chdir(project_root)
    return project_root


@pytest.fixture()
def conn(project: Path) -> sqlite3.Connection:
    connection = get_connection(project / ".jobctl" / "jobctl.db")
    try:
        yield connection
    finally:
        connection.close()


def test_run_apply_creates_materials_ready_tracker_entry(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    fake_vector_store,
) -> None:
    monkeypatch.setattr(apply_pipeline, "fetch_and_parse_jd", lambda _text, _client: make_jd())
    monkeypatch.setattr(
        apply_pipeline, "retrieve_relevant_experience", lambda *_args: {"nodes": [], "edges": []}
    )
    monkeypatch.setattr(apply_pipeline, "evaluate_fit", lambda *_args: make_eval())
    monkeypatch.setattr(apply_pipeline, "display_evaluation", lambda *_args: None)
    monkeypatch.setattr(apply_pipeline.Confirm, "ask", lambda *args, **kwargs: True)
    monkeypatch.setattr(apply_pipeline, "generate_resume_yaml", lambda *_args: make_resume())
    monkeypatch.setattr(
        apply_pipeline,
        "save_and_review",
        lambda _resume, output_dir: _write_file(
            output_dir / "artifacts" / "drafts" / "resume.yaml"
        ),
    )
    monkeypatch.setattr(apply_pipeline, "generate_cover_letter_yaml", lambda *_args: make_cover())
    monkeypatch.setattr(
        apply_pipeline,
        "save_and_review_cover_letter",
        lambda _cover, output_dir: _write_file(
            output_dir / "artifacts" / "drafts" / "cover-letter.yaml"
        ),
    )
    monkeypatch.setattr(
        apply_pipeline,
        "render_pdf",
        lambda _yaml_path, _template_name, output_path: _write_file(output_path, b"%PDF"),
    )

    app_id = apply_pipeline.run_apply(
        conn,
        "Senior Engineer JD",
        object(),
        default_config(),
        fake_vector_store,
    )

    application = get_application(conn, app_id)
    assert application["status"] == "materials_ready"
    assert application["resume_yaml_path"].endswith("artifacts/drafts/resume.yaml")
    assert application["resume_pdf_path"].endswith("artifacts/final/resume.pdf")
    assert application["cover_letter_yaml_path"].endswith("artifacts/drafts/cover-letter.yaml")
    assert application["cover_letter_pdf_path"].endswith("artifacts/final/cover-letter.pdf")


def test_run_apply_can_skip_material_generation(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    fake_vector_store,
) -> None:
    monkeypatch.setattr(apply_pipeline, "fetch_and_parse_jd", lambda _text, _client: make_jd())
    monkeypatch.setattr(
        apply_pipeline, "retrieve_relevant_experience", lambda *_args: {"nodes": [], "edges": []}
    )
    monkeypatch.setattr(apply_pipeline, "evaluate_fit", lambda *_args: make_eval())
    monkeypatch.setattr(apply_pipeline, "display_evaluation", lambda *_args: None)
    monkeypatch.setattr(apply_pipeline.Confirm, "ask", lambda *args, **kwargs: False)

    app_id = apply_pipeline.run_apply(
        conn,
        "Senior Engineer JD",
        object(),
        default_config(),
        fake_vector_store,
    )

    assert get_application(conn, app_id)["status"] == "evaluated"


def test_bus_confirm_marks_job_waiting_and_resumes() -> None:
    bus = AsyncEventBus()
    queue = bus.subscribe()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            apply_pipeline._bus_confirm,
            bus,
            "Generate tailored materials?",
            "yes_no",
            job_id="job-1",
        )

        waiting = _next_event(queue)
        assert isinstance(waiting, JobLifecycleEvent)
        assert waiting.phase == "waiting_for_user"
        request = _next_event(queue)
        assert isinstance(request, ConfirmationRequestedEvent)

        bus.publish(ConfirmationAnsweredEvent(confirm_id=request.confirm_id, answer=True))

        assert future.result(timeout=2) is True
        resumed = _next_event(queue)
        while isinstance(resumed, ConfirmationAnsweredEvent):
            resumed = _next_event(queue)
        assert isinstance(resumed, JobLifecycleEvent)
        assert resumed.phase == "running"


def _write_file(path: Path, content: bytes = b"yaml") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build systems"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="Raw JD",
    )


def make_eval() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Python"],
        gaps=[],
        recommendations=["Lead with Python"],
        summary="Strong fit.",
    )


def make_resume() -> ResumeYAML:
    return ResumeYAML(
        contact={"name": "Test User", "email": "user@example.com"},
        summary="Python engineer.",
        experience=[],
        skills={"Languages": ["Python"]},
        education=[],
        certifications=None,
        projects=None,
    )


def make_cover() -> CoverLetterYAML:
    return CoverLetterYAML(
        company="Acme",
        role="Senior Engineer",
        opening="I am interested.",
        body_paragraphs=["I built systems."],
        closing="Thank you.",
    )

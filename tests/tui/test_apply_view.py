"""ApplyView continuity tests."""

from __future__ import annotations

import sqlite3
import time
import asyncio
from pathlib import Path

import pytest

from jobctl.config import JobctlConfig
from jobctl.core.events import JobLifecycleEvent
from jobctl.db.connection import get_connection
from jobctl.generation.schemas import CoverLetterYAML
from jobctl.jobs.tracker import create_application, get_application, update_application
from jobctl.llm.schemas import ExtractedJD, FitEvaluation
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.apply import ApplyView
from tests.conftest import FakeLLMProvider


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _make_app(tmp_path: Path, conn: sqlite3.Connection, provider=None) -> JobctlApp:
    return JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=provider or FakeLLMProvider(),
        start_screen="apply",
    )


def _create_application(conn: sqlite3.Connection, tmp_path: Path) -> str:
    app_id = create_application(conn, "Acme", "Engineer", "https://example.com", _jd(), _eval())
    yaml_path = tmp_path / "exports" / "acme" / "artifacts" / "drafts" / "resume.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("contact:\n  name: Test\n", encoding="utf-8")
    update_application(conn, app_id, resume_yaml_path=str(yaml_path))
    return app_id


@pytest.mark.anyio
async def test_apply_render_pdf_persists_path_for_open(tmp_path: Path, monkeypatch) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    app_id = _create_application(conn, tmp_path)
    pdf_path = tmp_path / "resume.pdf"

    from jobctl.generation import renderer

    monkeypatch.setattr(renderer, "render_pdf", lambda *_args: pdf_path)
    monkeypatch.setattr(renderer, "output_pdf_path", lambda _path: pdf_path)

    app = _make_app(tmp_path, conn)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(ApplyView)
        view.action_render_pdf()
        await _wait_until(lambda: get_application(conn, app_id)["resume_pdf_path"] == str(pdf_path))

        assert view._current_row().resume_pdf_path == str(pdf_path)  # type: ignore[union-attr]

        await app.action_quit()

    conn.close()


@pytest.mark.anyio
async def test_apply_cover_letter_action_updates_tracker(tmp_path: Path, monkeypatch) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    app_id = _create_application(conn, tmp_path)
    provider = FakeLLMProvider(
        chat_reply=CoverLetterYAML(
            company="Acme",
            role="Engineer",
            opening="Hello",
            body_paragraphs=["Evidence."],
            closing="Thanks",
        ).model_dump_json()
    )
    pdf_path = tmp_path / "cover-letter.pdf"

    from jobctl.generation import renderer

    monkeypatch.setattr(renderer, "render_pdf", lambda *_args: pdf_path)
    monkeypatch.setattr(renderer, "output_pdf_path", lambda _path: pdf_path)

    app = _make_app(tmp_path, conn, provider)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ApplyView).action_generate_cover()
        await _wait_until(
            lambda: get_application(conn, app_id)["cover_letter_pdf_path"] == str(pdf_path)
        )

        application = get_application(conn, app_id)
        assert application["cover_letter_yaml_path"].endswith("cover-letter.yaml")
        assert application["cover_letter_pdf_path"] == str(pdf_path)

        await app.action_quit()

    conn.close()


@pytest.mark.anyio
async def test_apply_view_refreshes_on_apply_lifecycle_done(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    app = _make_app(tmp_path, conn)

    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(ApplyView)
        assert view._applications == []

        app_id = _create_application(conn, tmp_path)
        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-apply",
                kind="apply",
                label="Apply workflow",
                phase="done",
                message="Done",
            )
        )
        await _wait_until(lambda: view.current_app_id == app_id)

        await app.action_quit()

    conn.close()


def _jd() -> ExtractedJD:
    return ExtractedJD(
        title="Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="JD",
    )


def _eval() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Python"],
        gaps=[],
        recommendations=[],
        summary="Fit",
    )

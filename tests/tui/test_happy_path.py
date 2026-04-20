"""End-to-end TUI happy-path smoke coverage."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest
from textual.widgets import ContentSwitcher, TextArea

from jobctl.config import JobctlConfig
from jobctl.core.events import JobLifecycleEvent
from jobctl.db.connection import get_connection
from jobctl.jobs.tracker import create_application, get_application, update_application
from jobctl.llm.schemas import ExtractedJD, FitEvaluation
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.apply import ApplyView
from jobctl.tui.views.tracker import TrackerView
from tests.conftest import FakeLLMProvider


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


@pytest.mark.anyio
async def test_tui_happy_path_across_major_flows(tmp_path: Path, monkeypatch) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    app = JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=FakeLLMProvider(),
        start_screen="chat",
    )
    pdf_path = tmp_path / "resume.pdf"

    from jobctl.generation import renderer

    monkeypatch.setattr(renderer, "render_pdf", lambda *_args: pdf_path)
    monkeypatch.setattr(renderer, "output_pdf_path", lambda _path: pdf_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one("#main-switcher", ContentSwitcher)
        assert switcher.current == "chat"

        for key, expected in (
            ("ctrl+g", "graph"),
            ("ctrl+t", "tracker"),
            ("ctrl+r", "apply"),
            ("ctrl+e", "curate"),
            ("ctrl+s", "settings"),
            ("ctrl+j", "chat"),
        ):
            await pilot.press(key)
            await pilot.pause()
            assert switcher.current == expected

        app.bus.publish(
            JobLifecycleEvent(
                job_id="resume-job",
                kind="resume",
                label="Resume ingest",
                phase="running",
                message="Parsing",
            )
        )
        await _wait_until(lambda: "-visible" in app.query_one("#sidebar").classes)
        app.bus.publish(
            JobLifecycleEvent(
                job_id="resume-job",
                kind="resume",
                label="Resume ingest",
                phase="done",
                message="Done",
            )
        )

        app_id = _create_application(conn, tmp_path)
        app.show_view("apply")
        await pilot.pause()
        apply_view = app.query_one(ApplyView)
        apply_view._refresh_applications(preserve_current=False)
        apply_view.action_render_pdf()
        await _wait_until(lambda: get_application(conn, app_id)["resume_pdf_path"] == str(pdf_path))

        app.show_view("tracker")
        await pilot.pause()
        tracker = app.query_one(TrackerView)
        tracker.current_app_id = app_id
        tracker._show_application(app_id)
        app.query_one("#tracker-notes", TextArea).text = "Sent application."
        tracker.action_save_notes()
        await pilot.pause()
        assert get_application(conn, app_id)["notes"] == "Sent application."

        await app.action_quit()

    conn.close()


def _create_application(conn: sqlite3.Connection, tmp_path: Path) -> str:
    app_id = create_application(conn, "Acme", "Engineer", "https://example.com", _jd(), _eval())
    yaml_path = tmp_path / "exports" / "acme" / "artifacts" / "drafts" / "resume.yaml"
    yaml_path.parent.mkdir(parents=True)
    yaml_path.write_text("contact:\n  name: Test\n", encoding="utf-8")
    update_application(conn, app_id, resume_yaml_path=str(yaml_path))
    return app_id


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

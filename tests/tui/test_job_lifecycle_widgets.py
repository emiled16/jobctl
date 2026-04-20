"""Tests for spinner and sidebar background job lifecycle rendering."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from jobctl.config import JobctlConfig
from jobctl.core.events import JobLifecycleEvent
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.widgets.progress_panel import ProgressPanel
from jobctl.tui.widgets.spinner_status import SpinnerStatus
from tests.conftest import FakeLLMProvider


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _make_app(tmp_path: Path) -> JobctlApp:
    conn = get_connection(tmp_path / ".jobctl.db")
    return JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=FakeLLMProvider(),
        start_screen="chat",
    )


@pytest.mark.anyio
async def test_spinner_and_sidebar_track_lifecycle(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        spinner = app.query_one(SpinnerStatus)
        panel = app.query_one(ProgressPanel)

        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-1",
                kind="apply",
                label="Apply workflow",
                phase="running",
                message="Evaluating",
            )
        )
        await _wait_until(lambda: spinner.display is True)

        assert "Apply workflow" in str(spinner.renderable)
        assert "job-1" in panel._entries
        assert panel._entries["job-1"].state == "running"
        assert "-visible" in app.query_one("#sidebar").classes

        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-1",
                kind="apply",
                label="Apply workflow",
                phase="waiting_for_user",
                message="Generate materials?",
            )
        )
        await _wait_until(lambda: "Waiting for input" in str(spinner.renderable))
        assert panel._entries["job-1"].state == "waiting_for_user"

        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-1",
                kind="apply",
                label="Apply workflow",
                phase="done",
                message="Done",
            )
        )
        await _wait_until(lambda: panel._entries["job-1"].state == "done")
        assert "Done: Apply workflow" in str(spinner.renderable)
        assert panel._entries["job-1"].message == "Done"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_sidebar_keeps_error_state_visible(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.query_one(ProgressPanel)

        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-err",
                kind="resume",
                label="Resume ingest",
                phase="error",
                message="boom",
            )
        )
        await _wait_until(lambda: "job-err" in panel._entries)

        assert panel._entries["job-err"].state == "error"
        assert panel._entries["job-err"].message == "boom"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_spinner_handles_markup_like_error_message(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        spinner = app.query_one(SpinnerStatus)

        noisy_message = (
            "643 validation errors for ExtractedProfile\n"
            "facts.0.entity_type\n"
            "Field required [type=missing, input_value={'type': 'role', 'role': 'Engineer'}]"
        )
        app.bus.publish(
            JobLifecycleEvent(
                job_id="job-markup",
                kind="resume",
                label="Resume ingest",
                phase="error",
                message=noisy_message,
            )
        )

        await _wait_until(lambda: "validation errors for ExtractedProfile" in str(spinner.renderable))
        rendered = str(spinner.renderable)
        assert "validation errors for ExtractedProfile" in rendered
        assert "\n" not in rendered
        assert "input_value={'type': 'role'" in rendered

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

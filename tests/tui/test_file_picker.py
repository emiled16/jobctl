"""Tests for inline TUI file picker validation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from textual.css.query import NoMatches
from textual.widgets import Input

from jobctl.agent.state import WorkflowRequest
from jobctl.config import JobctlConfig
from jobctl.core.events import ConfirmationRequestedEvent
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.chat import ChatView
from jobctl.tui.widgets.file_picker import FilePicker
from tests.conftest import FakeLLMProvider


class _WorkflowRunner:
    def __init__(self) -> None:
        self.requests: list[WorkflowRequest] = []

    async def submit_workflow(self, request: WorkflowRequest) -> None:
        self.requests.append(request)


def _make_app(tmp_path: Path, runner: _WorkflowRunner) -> JobctlApp:
    conn = get_connection(tmp_path / ".jobctl.db")
    app = JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=FakeLLMProvider(),
        start_screen="chat",
    )
    app._runner = runner
    return app


def _request() -> ConfirmationRequestedEvent:
    return ConfirmationRequestedEvent(
        question="Pick a resume",
        confirm_id="resume-pick",
        kind="file_pick_resume",
    )


@pytest.mark.anyio
async def test_resume_file_picker_rejects_invalid_paths(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._render_event(_request())
        await pilot.pause()

        picker = app.query_one(FilePicker)
        input_widget = picker.query_one("#file-picker-input", Input)
        input_widget.value = ""
        picker._submit_selection()
        await pilot.pause()

        assert picker._error_message == "Choose a resume file path before continuing."
        assert runner.requests == []

        input_widget.value = str(tmp_path)
        picker._submit_selection()
        await pilot.pause()

        assert picker._error_message == "Choose a resume file, not a directory."
        assert runner.requests == []

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_resume_file_picker_submits_structured_workflow(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)
    resume_path = tmp_path / "resume.md"
    resume_path.write_text("# Resume\nPython engineer", encoding="utf-8")

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._render_event(_request())
        await pilot.pause()

        picker = app.query_one(FilePicker)
        picker.query_one("#file-picker-input", Input).value = str(resume_path)
        picker._submit_selection()
        await pilot.pause()

        assert runner.requests == [
            {"kind": "resume_ingest", "payload": {"path": str(resume_path)}}
        ]
        with pytest.raises(NoMatches):
            app.query_one(FilePicker)

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

"""Tests for inline Apply workflow starts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from textual.css.query import NoMatches
from textual.widgets import Input, TextArea

from jobctl.agent.state import WorkflowRequest
from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.chat import ChatView
from jobctl.tui.widgets.apply_input import ApplyInput
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


@pytest.mark.anyio
async def test_apply_slash_without_payload_requires_mode_choice(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply")
        await pilot.pause()

        widget = app.query_one(ApplyInput)
        widget._submit()
        await pilot.pause()

        assert widget._error_message == "Choose whether to paste JD text or use a URL."
        assert runner.requests == []

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_apply_input_url_mode_requires_value(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply")
        await pilot.pause()

        widget = app.query_one(ApplyInput)
        widget._set_mode("url")
        widget._submit()
        await pilot.pause()

        assert widget._error_message == "Enter a job URL."
        assert runner.requests == []

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_apply_input_text_mode_requires_value(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply")
        await pilot.pause()

        widget = app.query_one(ApplyInput)
        widget._set_mode("text")
        widget._submit()
        await pilot.pause()

        assert widget._error_message == "Paste the job description text."
        assert runner.requests == []

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_apply_input_submits_url(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply")
        await pilot.pause()

        widget = app.query_one(ApplyInput)
        widget._set_mode("url")
        widget.query_one("#apply-input-url", Input).value = "https://example.com/job"
        widget._submit()
        await pilot.pause()

        assert runner.requests == [
            {"kind": "apply", "payload": {"url_or_text": "https://example.com/job"}}
        ]
        with pytest.raises(NoMatches):
            app.query_one(ApplyInput)

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_apply_input_submits_multiline_pasted_jd(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    pasted = (
        "Senior Platform Engineer\n"
        "Responsibilities:\n"
        "- Build distributed systems\n"
        "- Mentor engineers\n"
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply")
        await pilot.pause()

        widget = app.query_one(ApplyInput)
        widget._set_mode("text")
        widget.query_one("#apply-input-text", TextArea).text = pasted
        widget._submit()
        await pilot.pause()

        assert runner.requests == [
            {"kind": "apply", "payload": {"url_or_text": pasted.strip()}}
        ]
        with pytest.raises(NoMatches):
            app.query_one(ApplyInput)

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_apply_slash_with_payload_submits_directly(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/apply https://example.com/job")
        await pilot.pause()

        assert runner.requests == [
            {"kind": "apply", "payload": {"url_or_text": "https://example.com/job"}}
        ]
        with pytest.raises(NoMatches):
            app.query_one(ApplyInput)

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_refine_resume_slash_submits_workflow(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)
        chat._handle_submission("/refine resume")
        await pilot.pause()

        assert runner.requests == [{"kind": "resume_refinement", "payload": {}}]

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

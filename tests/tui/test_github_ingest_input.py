"""Tests for inline GitHub ingest input."""

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
from jobctl.tui.widgets.github_ingest_input import GitHubIngestInput
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
        question="Which GitHub profile or repos should I ingest?",
        confirm_id="github-input",
        kind="github_user",
    )


@pytest.mark.anyio
async def test_github_ingest_input_rejects_empty_value(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ChatView)._render_event(_request())
        await pilot.pause()

        widget = app.query_one(GitHubIngestInput)
        widget._submit()
        await pilot.pause()

        assert widget._error_message == "Enter a GitHub username, profile URL, or repo URL."
        assert runner.requests == []

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_github_ingest_input_submits_structured_workflow(tmp_path: Path) -> None:
    runner = _WorkflowRunner()
    app = _make_app(tmp_path, runner)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ChatView)._render_event(_request())
        await pilot.pause()

        widget = app.query_one(GitHubIngestInput)
        widget.query_one("#github-ingest-input", Input).value = (
            "octocat https://github.com/example/repo"
        )
        widget._submit()
        await pilot.pause()

        assert runner.requests == [
            {
                "kind": "github_ingest",
                "payload": {
                    "username_or_urls": ["octocat", "https://github.com/example/repo"]
                },
            }
        ]
        with pytest.raises(NoMatches):
            app.query_one(GitHubIngestInput)

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

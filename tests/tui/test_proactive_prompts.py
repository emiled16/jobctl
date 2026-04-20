"""Regression tests for proactive Chat workflow prompts."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.chat import ChatView
from jobctl.tui.widgets.file_picker import FilePicker
from jobctl.tui.widgets.github_ingest_input import GitHubIngestInput
from tests.conftest import FakeLLMProvider


async def _wait_until(predicate, *, timeout: float = 2.0) -> None:
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
        provider=FakeLLMProvider(chat_reply="ok"),
        start_screen="chat",
    )


@pytest.mark.anyio
async def test_resume_mention_opens_resume_file_picker(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ChatView)._handle_submission("I want to ingest my resume")
        await _wait_until(lambda: bool(app.query(FilePicker)))

        assert app.query_one(FilePicker).request.kind == "file_pick_resume"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_github_mention_opens_github_input(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ChatView)._handle_submission("Please ingest my GitHub repos")
        await _wait_until(lambda: bool(app.query(GitHubIngestInput)))

        assert app.query_one(GitHubIngestInput).request.kind == "github_user"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

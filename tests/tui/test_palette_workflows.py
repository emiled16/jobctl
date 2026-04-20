"""Tests for command palette workflow actions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from textual.widgets import ContentSwitcher

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.widgets.apply_input import ApplyInput
from jobctl.tui.widgets.file_picker import FilePicker
from jobctl.tui.widgets.github_ingest_input import GitHubIngestInput
from tests.conftest import FakeLLMProvider


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
async def test_palette_workflow_commands_open_real_inputs(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        commands = {command.label: command for command in app.palette_commands()}
        assert "Slash: /apply" not in commands
        assert "Slash: /ingest resume" not in commands
        assert "Slash: /ingest github" not in commands

        commands["Workflow: Ingest resume"].action()
        await pilot.pause()
        assert app.query_one(FilePicker).request.kind == "file_pick_resume"

        commands["Workflow: Ingest GitHub"].action()
        await pilot.pause()
        assert app.query_one(GitHubIngestInput).request.kind == "github_user"

        commands["Workflow: Apply"].action()
        await pilot.pause()
        assert app.query_one(ApplyInput).request.kind == "apply_input"

        commands["Workflow: Curate"].action()
        await pilot.pause()
        assert app.query_one("#main-switcher", ContentSwitcher).current == "curate"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

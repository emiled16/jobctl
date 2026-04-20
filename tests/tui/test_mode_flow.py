"""TUI tests for confirmed agent mode changes."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

from jobctl.agent.session import load_session
from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.chat import ChatView
from jobctl.tui.widgets.confirm_card import InlineConfirmCard
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
async def test_mode_slash_persists_after_confirmation(tmp_path: Path) -> None:
    app = _make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(ChatView)._handle_submission("/mode graph_qa")
        await _wait_until(lambda: bool(app.query(InlineConfirmCard)))

        app.query_one(InlineConfirmCard).action_answer_yes()
        await _wait_until(
            lambda: (load_session(app.conn, app.session_id) or {}).get("mode") == "graph_qa"
        )

        assert (load_session(app.conn, app.session_id) or {}).get("mode") == "graph_qa"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

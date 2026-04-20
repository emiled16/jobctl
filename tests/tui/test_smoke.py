"""Textual ``Pilot`` smoke test that boots the TUI and switches views."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import JobctlApp
from tests.conftest import FakeLLMProvider


def _make_app(tmp_path: Path) -> JobctlApp:
    conn = get_connection(tmp_path / ".jobctl.db")
    config = JobctlConfig()
    provider = FakeLLMProvider(chat_reply="hello world")
    return JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=config,
        provider=provider,
        start_screen="chat",
    )


@pytest.mark.asyncio
async def test_tui_boots_and_navigates_all_views(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ChatView"

        await pilot.press("g", "t")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TrackerView"

        await pilot.press("g", "g")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "GraphView"

        await pilot.press("g", "u")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "CurateView"

        await pilot.press("g", "a")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ApplyView"

        await pilot.press("g", "comma")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "SettingsView"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

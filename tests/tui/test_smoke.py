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


@pytest.mark.anyio
async def test_tui_boots_and_navigates_all_views(tmp_path: Path) -> None:
    from textual.widgets import ContentSwitcher

    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one("#main-switcher", ContentSwitcher)
        assert switcher.current == "chat"

        await pilot.press("ctrl+t")
        await pilot.pause()
        assert switcher.current == "tracker"

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert switcher.current == "graph"

        await pilot.press("ctrl+e")
        await pilot.pause()
        assert switcher.current == "curate"

        await pilot.press("ctrl+r")
        await pilot.pause()
        assert switcher.current == "apply"

        await pilot.press("ctrl+s")
        await pilot.pause()
        assert switcher.current == "settings"

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

"""Textual ``Pilot`` smoke test that boots the TUI and switches views."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.tui.app import SCREEN_NAMES, JobctlApp
from jobctl.tui.views.chat import ChatView
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


@pytest.mark.anyio
async def test_global_navigation_bindings_and_g_chords(tmp_path: Path) -> None:
    from textual.widgets import ContentSwitcher

    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one("#main-switcher", ContentSwitcher)

        for key, expected in (
            ("ctrl+j", "chat"),
            ("ctrl+g", "graph"),
            ("ctrl+t", "tracker"),
            ("ctrl+r", "apply"),
            ("ctrl+e", "curate"),
            ("ctrl+s", "settings"),
        ):
            await pilot.press(key)
            await pilot.pause()
            assert switcher.current == expected

        await pilot.press("ctrl+j")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is None

        for keys, expected in (
            (("g", "g"), "graph"),
            (("g", "t"), "tracker"),
            (("g", "a"), "apply"),
            (("g", "u"), "curate"),
            (("g", "comma"), "settings"),
            (("g", "c"), "chat"),
        ):
            await pilot.press(*keys)
            await pilot.pause()
            assert switcher.current == expected

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_slash_navigation_uses_content_switcher(tmp_path: Path) -> None:
    from textual.widgets import ContentSwitcher

    app = _make_app(tmp_path)

    def fail_switch_screen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("slash navigation must not call switch_screen")

    app.switch_screen = fail_switch_screen  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one("#main-switcher", ContentSwitcher)
        chat = app.query_one(ChatView)

        for name in ("graph", "tracker", "apply", "curate", "settings"):
            chat._handle_submission(f"/{name}")
            await pilot.pause()
            assert switcher.current == name

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()


@pytest.mark.anyio
async def test_palette_view_commands_switch_views_directly(tmp_path: Path) -> None:
    from textual.widgets import ContentSwitcher

    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        switcher = app.query_one("#main-switcher", ContentSwitcher)

        commands = {command.label: command for command in app.palette_commands()}
        for name in SCREEN_NAMES:
            commands[f"View: {name.capitalize()}"].action()
            await pilot.pause()
            assert switcher.current == name

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

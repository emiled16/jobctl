"""Tests for Graph and Tracker safety polish."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from textual.widgets import Input, TextArea, Tree

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_node, get_node
from jobctl.jobs.tracker import create_application, get_application
from jobctl.llm.schemas import ExtractedJD, FitEvaluation
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.graph import GraphView
from jobctl.tui.views.tracker import TrackerView
from tests.conftest import FakeLLMProvider


def _make_app(tmp_path: Path, conn: sqlite3.Connection, start_screen: str) -> JobctlApp:
    return JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=FakeLLMProvider(),
        start_screen=start_screen,
    )


@pytest.mark.anyio
async def test_graph_edit_uses_tree_cursor_without_details(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    node_id = add_node(conn, "skill", "Python", {}, "Python")
    app = _make_app(tmp_path, conn, "graph")

    async with app.run_test() as pilot:
        await pilot.pause()
        graph = app.query_one(GraphView)
        tree = app.query_one("#graph-tree", Tree)
        tree.move_cursor(tree.root.children[0].children[0])
        graph.current_node_id = None

        graph.action_edit_selected()
        await pilot.pause()

        assert graph.current_node_id == node_id
        assert "Python" in app.query_one("#graph-editor", TextArea).text

        await app.action_quit()

    conn.close()


@pytest.mark.anyio
async def test_graph_delete_confirmed_removes_node(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    node_id = add_node(conn, "skill", "Python", {}, "Python")
    app = _make_app(tmp_path, conn, "graph")

    async with app.run_test() as pilot:
        await pilot.pause()
        graph = app.query_one(GraphView)
        graph._delete_node_confirmed(node_id)
        await pilot.pause()

        with pytest.raises(KeyError):
            get_node(conn, node_id)

        await app.action_quit()

    conn.close()


@pytest.mark.anyio
async def test_escape_clears_graph_search_before_blur(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    add_node(conn, "skill", "Python", {}, "Python")
    app = _make_app(tmp_path, conn, "graph")

    async with app.run_test() as pilot:
        await pilot.pause()
        search = app.query_one("#graph-search", Input)
        search.value = "Python"
        search.focus()
        await pilot.pause()

        app.action_blur_focus()
        await pilot.pause()

        assert search.value == ""
        assert app.focused is search

        app.action_blur_focus()
        await pilot.pause()
        assert app.focused is None

        await app.action_quit()

    conn.close()


@pytest.mark.anyio
async def test_tracker_notes_save_status(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    app_id = create_application(conn, "Acme", "Engineer", None, _jd(), _eval())
    app = _make_app(tmp_path, conn, "tracker")

    async with app.run_test() as pilot:
        await pilot.pause()
        tracker = app.query_one(TrackerView)
        tracker.current_app_id = app_id
        tracker._show_application(app_id)
        notes = app.query_one("#tracker-notes", TextArea)
        notes.text = "Follow up Friday"

        tracker.action_save_notes()
        await pilot.pause()

        assert get_application(conn, app_id)["notes"] == "Follow up Friday"
        assert "Notes saved" in str(app.query_one("#tracker-save-status").renderable)

        await app.action_quit()

    conn.close()


def _jd() -> ExtractedJD:
    return ExtractedJD(
        title="Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="JD",
    )


def _eval() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Python"],
        gaps=[],
        recommendations=[],
        summary="Fit",
    )

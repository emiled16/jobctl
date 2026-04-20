"""Tracker view stub; filled in by T16."""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label


class TrackerView(Screen):
    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

    def compose(self) -> ComposeResult:
        yield Label("Tracker view (stub)")

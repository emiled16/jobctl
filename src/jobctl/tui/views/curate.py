"""Curate view stub; filled in by T39."""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from jobctl.core.jobs.runner import BackgroundJobRunner


class CurateView(Screen):
    def __init__(self, conn: sqlite3.Connection, runner: BackgroundJobRunner) -> None:
        super().__init__()
        self.conn = conn
        self.runner = runner

    def compose(self) -> ComposeResult:
        yield Label("Curate view (stub)")

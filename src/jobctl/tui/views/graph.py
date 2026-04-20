"""Graph view stub; filled in by T15."""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from jobctl.llm.base import LLMProvider


class GraphView(Screen):
    def __init__(self, conn: sqlite3.Connection, *, provider: LLMProvider | None = None) -> None:
        super().__init__()
        self.conn = conn
        self.provider = provider

    def compose(self) -> ComposeResult:
        yield Label("Graph view (stub)")

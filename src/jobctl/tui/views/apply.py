"""Apply view stub; filled in by T17 / T43."""

from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from jobctl.core.events import AsyncEventBus
from jobctl.llm.base import LLMProvider


class ApplyView(Screen):
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: LLMProvider,
        bus: AsyncEventBus,
    ) -> None:
        super().__init__()
        self.conn = conn
        self.provider = provider
        self.bus = bus

    def compose(self) -> ComposeResult:
        yield Label("Apply view (stub)")

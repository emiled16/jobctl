"""Chat view stub; filled in by T18 / T26."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label


class ChatView(Screen):
    def compose(self) -> ComposeResult:
        yield Label("Chat view (stub)")

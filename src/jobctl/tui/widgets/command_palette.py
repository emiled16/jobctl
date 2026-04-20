"""Fuzzy-search command palette overlay (stub; expanded in T13)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Label


class CommandPaletteOverlay(ModalScreen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Close")]

    def __init__(self, commands) -> None:
        super().__init__()
        self.commands = commands

    def compose(self) -> ComposeResult:
        yield Label("Command palette (stub)")

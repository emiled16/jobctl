"""Keybinding help overlay (stub; expanded in T14)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Label


class KeybindingHelpOverlay(ModalScreen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("q", "app.pop_screen", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Keybindings help (stub)")

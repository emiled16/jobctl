"""Fuzzy-search command palette overlay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static


@dataclass
class PaletteCommand:
    label: str
    description: str
    action: Callable[[], Any]


def _score(query: str, text: str) -> int:
    """Simple case-insensitive substring match score. Lower is better."""
    if not query:
        return 0
    text_lower = text.lower()
    query_lower = query.lower()
    if query_lower not in text_lower:
        return -1
    return text_lower.index(query_lower)


class CommandPaletteOverlay(ModalScreen[None]):
    """Fuzzy-searchable modal list of ``PaletteCommand`` objects."""

    DEFAULT_CSS = """
    CommandPaletteOverlay {
        align: center middle;
    }
    #palette-container {
        width: 70%;
        max-height: 80%;
        background: #181825;
        border: solid #45475a;
        padding: 1;
    }
    #palette-input {
        dock: top;
    }
    """
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("enter", "activate", "Run"),
        Binding("down", "cursor_down", "Down", show=False, priority=True),
        Binding("up", "cursor_up", "Up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", show=False, priority=True),
        Binding("ctrl+n", "cursor_down", "Down", show=False, priority=True),
        Binding("ctrl+p", "cursor_up", "Up", show=False, priority=True),
    ]

    def __init__(self, commands: list[PaletteCommand]) -> None:
        super().__init__()
        self.commands = list(commands)
        self._filtered: list[PaletteCommand] = list(commands)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Input(placeholder="Type to filter commands", id="palette-input"),
            ListView(id="palette-list"),
            Static("", id="palette-description"),
            id="palette-container",
        )

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()
        self._refresh_list("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-input":
            self._refresh_list(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "palette-input":
            self.action_activate()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "palette-list":
            return
        index = event.list_view.index or 0
        if 0 <= index < len(self._filtered):
            self.query_one("#palette-description", Static).update(
                self._filtered[index].description
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "palette-list":
            self.action_activate()

    def action_activate(self) -> None:
        list_view = self.query_one("#palette-list", ListView)
        index = list_view.index or 0
        if 0 <= index < len(self._filtered):
            command = self._filtered[index]
            self.app.pop_screen()
            command.action()

    def _move_index(self, delta: int) -> None:
        list_view = self.query_one("#palette-list", ListView)
        if not self._filtered:
            return
        current = list_view.index or 0
        new_index = max(0, min(len(self._filtered) - 1, current + delta))
        list_view.index = new_index
        # Re-trigger description refresh for the new selection.
        self.query_one("#palette-description", Static).update(
            self._filtered[new_index].description
        )

    def action_cursor_down(self) -> None:
        self._move_index(1)

    def action_cursor_up(self) -> None:
        self._move_index(-1)

    def action_page_down(self) -> None:
        self._move_index(10)

    def action_page_up(self) -> None:
        self._move_index(-10)

    def _refresh_list(self, query: str) -> None:
        scored = [
            (score, cmd)
            for cmd in self.commands
            if (score := _score(query, cmd.label)) >= 0
            or (not query and True)
        ]
        scored.sort(key=lambda pair: (pair[0], pair[1].label))
        self._filtered = [cmd for _, cmd in scored]
        list_view = self.query_one("#palette-list", ListView)
        list_view.clear()
        for cmd in self._filtered:
            list_view.append(ListItem(Static(cmd.label)))
        description = self.query_one("#palette-description", Static)
        if self._filtered:
            list_view.index = 0
            description.update(self._filtered[0].description)
        else:
            description.update("No matches.")


__all__ = ["CommandPaletteOverlay", "PaletteCommand"]

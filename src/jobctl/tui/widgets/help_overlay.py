"""Modal keybinding help overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label


class KeybindingHelpOverlay(ModalScreen[None]):
    """Renders every active keybinding grouped by source screen."""

    DEFAULT_CSS = """
    KeybindingHelpOverlay {
        align: center middle;
    }
    #help-container {
        width: 80%;
        max-height: 85%;
        background: #181825;
        border: solid #45475a;
        padding: 1;
    }
    """
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("q", "app.pop_screen", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Keybindings", id="help-title"),
            DataTable(id="help-table"),
            id="help-container",
        )

    def on_mount(self) -> None:
        table = self.query_one("#help-table", DataTable)
        table.add_columns("Context", "Keys", "Description")
        rows = self._collect_bindings()
        for row in rows:
            table.add_row(*row)

    def _collect_bindings(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        rows.extend(self._bindings_from("App", self.app))
        screen_stack = getattr(self.app, "screen_stack", [])
        for screen in screen_stack:
            name = screen.__class__.__name__
            if name == "KeybindingHelpOverlay":
                continue
            rows.extend(self._bindings_from(name, screen))
        return rows

    def _bindings_from(self, context: str, obj: object) -> list[tuple[str, str, str]]:
        bindings = getattr(obj, "BINDINGS", None) or []
        result: list[tuple[str, str, str]] = []
        for binding in bindings:
            keys, description = _binding_fields(binding)
            if description:
                result.append((context, keys, description))
        return result


def _binding_fields(binding) -> tuple[str, str]:
    if isinstance(binding, tuple):
        if len(binding) >= 3:
            return binding[0], binding[2]
        if len(binding) == 2:
            return binding[0], binding[1]
        return binding[0], ""
    keys = getattr(binding, "key", "")
    description = getattr(binding, "description", "") or getattr(binding, "action", "")
    return str(keys), str(description)


__all__ = ["KeybindingHelpOverlay"]

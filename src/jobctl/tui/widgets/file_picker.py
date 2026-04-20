"""Inline Textual file-picker mounted inside the chat message log."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DirectoryTree, Input

from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)


class FilePicker(Vertical):
    """Inline file picker combining a directory tree with a path input."""

    DEFAULT_CSS = """
    FilePicker {
        border: round #45475a;
        padding: 0 1;
        margin: 1 0;
        background: #313244;
        height: 20;
    }
    FilePicker DirectoryTree {
        height: 14;
    }
    FilePicker Input {
        margin-top: 1;
    }
    FilePicker Horizontal {
        margin-top: 1;
    }
    FilePicker Button {
        margin: 0 1;
    }
    """

    class FileSelected(Message):
        def __init__(self, sender: Widget, path: Path) -> None:
            super().__init__()
            self.sender = sender
            self.path = path

    def __init__(
        self,
        request: ConfirmationRequestedEvent,
        *,
        bus: AsyncEventBus,
        start_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.request = request
        self.bus = bus
        self._start_path = start_path or Path.cwd()
        self._input: Input | None = None
        self._tree: DirectoryTree | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            DirectoryTree(str(self._start_path), id="file-picker-tree"),
            Input(
                placeholder="Or type a path...",
                id="file-picker-input",
                value=str(self._start_path),
            ),
            Horizontal(
                Button("Select", id="file-picker-select", variant="success"),
                Button("Cancel", id="file-picker-cancel", variant="error"),
            ),
        )

    def on_mount(self) -> None:
        self._input = self.query_one("#file-picker-input", Input)
        self._tree = self.query_one("#file-picker-tree", DirectoryTree)
        self._input.focus()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        if self._input is not None:
            self._input.value = str(event.path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "file-picker-input":
            return
        event.stop()
        self._submit_selection()

    def _submit_selection(self) -> None:
        path = self._current_path()
        payload = {"path": str(path) if path else ""}
        if path is not None:
            self.post_message(self.FileSelected(self, path))
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=path is not None,
                payload=payload,
            )
        )
        self.remove()

    def _current_path(self) -> Path | None:
        if self._input is None:
            return None
        text = self._input.value.strip()
        if not text:
            return None
        return Path(text).expanduser()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-picker-select":
            self._submit_selection()
            return
        if event.button.id == "file-picker-cancel":
            self.bus.publish(
                ConfirmationAnsweredEvent(
                    confirm_id=self.request.confirm_id,
                    answer=False,
                )
            )
            self.remove()


__all__ = ["FilePicker"]

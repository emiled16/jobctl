"""Inline Textual file-picker mounted inside the chat message log."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DirectoryTree, Input, Static

from jobctl.core.events import (
    AgentDoneEvent,
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)
from jobctl.ingestion.resume import SUPPORTED_RESUME_EXTENSIONS


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
    FilePicker #file-picker-error {
        color: #f38ba8;
        min-height: 1;
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
        self._error_message = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            DirectoryTree(str(self._start_path), id="file-picker-tree"),
            Input(
                placeholder="Or type a path...",
                id="file-picker-input",
                value=str(self._start_path),
            ),
            Static("", id="file-picker-error"),
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
        if self.request.kind == "file_pick_resume":
            error = self._validate_resume_path(path)
            if error is not None:
                self._show_error(error)
                return

        payload = {"path": str(path) if path else ""}
        if path is not None:
            self.post_message(self.FileSelected(self, path))
        if self.request.kind == "file_pick_resume" and path is not None:
            if not self._submit_resume_workflow(path):
                return
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

    def _validate_resume_path(self, path: Path | None) -> str | None:
        if path is None:
            return "Choose a resume file path before continuing."
        if not path.exists():
            return f"No file exists at {path}."
        if path.is_dir():
            return "Choose a resume file, not a directory."
        if path.suffix.lower() not in SUPPORTED_RESUME_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_RESUME_EXTENSIONS))
            return f"Unsupported resume format. Use one of: {supported}."
        return None

    def _show_error(self, message: str) -> None:
        self._error_message = message
        self.query_one("#file-picker-error", Static).update(message)

    def _submit_resume_workflow(self, path: Path) -> bool:
        runner = getattr(self.app, "agent_runner", None)
        if runner is None or not hasattr(runner, "submit_workflow"):
            self._show_error("Resume ingestion requires an agent runner.")
            return False
        from jobctl.agent.state import make_workflow_request

        request = make_workflow_request("resume_ingest", {"path": str(path)})
        asyncio.create_task(runner.submit_workflow(request))
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-picker-select":
            self._submit_selection()
            return
        if event.button.id == "file-picker-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.bus.publish(AgentDoneEvent(role="assistant", content="Canceled."))
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=False,
            )
        )
        self.remove()


__all__ = ["FilePicker"]

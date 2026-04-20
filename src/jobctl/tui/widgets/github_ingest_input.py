"""Inline GitHub ingest input used by Chat and workflow prompts."""

from __future__ import annotations

import asyncio
import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static

from jobctl.agent.state import make_workflow_request
from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)


class GitHubIngestInput(Vertical):
    """Collect GitHub usernames, profile URLs, or repo URLs."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    GitHubIngestInput {
        border: round #45475a;
        padding: 0 1;
        margin: 1 0;
        background: #313244;
    }
    GitHubIngestInput #github-ingest-error {
        color: #f38ba8;
        min-height: 1;
    }
    GitHubIngestInput Button {
        margin: 0 1;
    }
    """

    def __init__(self, request: ConfirmationRequestedEvent, *, bus: AsyncEventBus) -> None:
        super().__init__()
        self.request = request
        self.bus = bus
        self._error_message = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.request.question, id="github-ingest-question"),
            Input(
                placeholder="GitHub username, profile URL, or repo URLs",
                id="github-ingest-input",
            ),
            Static("", id="github-ingest-error"),
            Horizontal(
                Button("Start", id="github-ingest-start", variant="success"),
                Button("Cancel", id="github-ingest-cancel", variant="error"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#github-ingest-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "github-ingest-input":
            return
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "github-ingest-start":
            self._submit()
            return
        if event.button.id == "github-ingest-cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=False,
            )
        )
        self.remove()

    def _submit(self) -> None:
        value = self.query_one("#github-ingest-input", Input).value
        targets = self._parse_targets(value)
        if not targets:
            self._show_error("Enter a GitHub username, profile URL, or repo URL.")
            return
        runner = getattr(self.app, "agent_runner", None)
        if runner is None or not hasattr(runner, "submit_workflow"):
            self._show_error("GitHub ingestion requires an agent runner.")
            return

        request = make_workflow_request("github_ingest", {"username_or_urls": targets})
        asyncio.create_task(runner.submit_workflow(request))
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=True,
                payload={"username_or_urls": targets},
            )
        )
        self.remove()

    def _parse_targets(self, value: str) -> list[str]:
        return [part for part in re.split(r"[\s,]+", value.strip()) if part]

    def _show_error(self, message: str) -> None:
        self._error_message = message
        self.query_one("#github-ingest-error", Static).update(message)


__all__ = ["GitHubIngestInput"]

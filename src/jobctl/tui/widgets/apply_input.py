"""Inline Apply workflow input used by Chat and palette starts."""

from __future__ import annotations

import asyncio

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


class ApplyInput(Vertical):
    """Collect a job posting URL or pasted JD text."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    ApplyInput {
        border: round #45475a;
        padding: 0 1;
        margin: 1 0;
        background: #313244;
    }
    ApplyInput #apply-input-error {
        color: #f38ba8;
        min-height: 1;
    }
    ApplyInput Button {
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
            Static(self.request.question, id="apply-input-question"),
            Input(
                placeholder="Job URL or pasted JD text",
                id="apply-input-value",
            ),
            Static("", id="apply-input-error"),
            Horizontal(
                Button("Start", id="apply-input-start", variant="success"),
                Button("Cancel", id="apply-input-cancel", variant="error"),
            ),
        )

    def on_mount(self) -> None:
        self.query_one("#apply-input-value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "apply-input-value":
            return
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-input-start":
            self._submit()
            return
        if event.button.id == "apply-input-cancel":
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
        value = self.query_one("#apply-input-value", Input).value.strip()
        if not value:
            self._show_error("Enter a job URL or pasted job description.")
            return
        runner = getattr(self.app, "agent_runner", None)
        if runner is None or not hasattr(runner, "submit_workflow"):
            self._show_error("Apply requires an agent runner.")
            return

        request = make_workflow_request("apply", {"url_or_text": value})
        asyncio.create_task(runner.submit_workflow(request))
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=True,
                payload={"url_or_text": value},
            )
        )
        self.remove()

    def _show_error(self, message: str) -> None:
        self._error_message = message
        self.query_one("#apply-input-error", Static).update(message)


__all__ = ["ApplyInput"]

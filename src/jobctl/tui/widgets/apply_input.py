"""Inline Apply workflow input used by Chat and palette starts.

The widget first asks the user whether they want to provide a job URL or
paste the full job description text. Based on that choice the input switches
between a single-line ``Input`` (for URLs) and a multi-line ``TextArea``
(for pasted JDs) so pasting multi-paragraph descriptions works reliably.
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static, TextArea

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
    ApplyInput #apply-input-url-row,
    ApplyInput #apply-input-text-row,
    ApplyInput #apply-input-submit-row {
        display: none;
    }
    ApplyInput.mode-url #apply-input-choice-row,
    ApplyInput.mode-text #apply-input-choice-row {
        display: none;
    }
    ApplyInput.mode-url #apply-input-url-row,
    ApplyInput.mode-url #apply-input-submit-row {
        display: block;
    }
    ApplyInput.mode-text #apply-input-text-row,
    ApplyInput.mode-text #apply-input-submit-row {
        display: block;
    }
    ApplyInput #apply-input-text {
        height: 10;
    }
    ApplyInput #apply-input-hint {
        color: #a6adc8;
        margin-bottom: 1;
    }
    """

    def __init__(self, request: ConfirmationRequestedEvent, *, bus: AsyncEventBus) -> None:
        super().__init__()
        self.request = request
        self.bus = bus
        self._error_message = ""
        self._mode: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(self.request.question, id="apply-input-question")
        yield Static(
            "How would you like to provide the job description?",
            id="apply-input-hint",
        )
        yield Horizontal(
            Button("Paste JD text", id="apply-input-mode-text", variant="primary"),
            Button("Use URL", id="apply-input-mode-url"),
            Button("Cancel", id="apply-input-cancel-choice", variant="error"),
            id="apply-input-choice-row",
        )
        yield Horizontal(
            Input(
                placeholder="https://example.com/jobs/123",
                id="apply-input-url",
            ),
            id="apply-input-url-row",
        )
        yield Vertical(
            Static(
                "Paste the full job description below (multi-line supported).",
                id="apply-input-text-label",
            ),
            TextArea(id="apply-input-text"),
            id="apply-input-text-row",
        )
        yield Static("", id="apply-input-error")
        yield Horizontal(
            Button("Start", id="apply-input-start", variant="success"),
            Button("Back", id="apply-input-back"),
            Button("Cancel", id="apply-input-cancel", variant="error"),
            id="apply-input-submit-row",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "apply-input-url":
            return
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "apply-input-mode-url":
            self._set_mode("url")
        elif button_id == "apply-input-mode-text":
            self._set_mode("text")
        elif button_id == "apply-input-start":
            self._submit()
        elif button_id == "apply-input-back":
            self._set_mode(None)
        elif button_id in ("apply-input-cancel", "apply-input-cancel-choice"):
            self.action_cancel()

    def _set_mode(self, mode: str | None) -> None:
        self._mode = mode
        self.remove_class("mode-url")
        self.remove_class("mode-text")
        self._show_error("")
        if mode == "url":
            self.add_class("mode-url")
            try:
                self.query_one("#apply-input-url", Input).focus()
            except Exception:
                pass
        elif mode == "text":
            self.add_class("mode-text")
            try:
                self.query_one("#apply-input-text", TextArea).focus()
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=False,
            )
        )
        self.remove()

    def _submit(self) -> None:
        if self._mode == "url":
            value = self.query_one("#apply-input-url", Input).value.strip()
            empty_msg = "Enter a job URL."
        elif self._mode == "text":
            value = self.query_one("#apply-input-text", TextArea).text.strip()
            empty_msg = "Paste the job description text."
        else:
            self._show_error("Choose whether to paste JD text or use a URL.")
            return

        if not value:
            self._show_error(empty_msg)
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

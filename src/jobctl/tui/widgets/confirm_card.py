"""Inline confirmation card used inside ``ChatView``.

The widget subscribes to ``ConfirmationRequestedEvent`` and replies with
``ConfirmationAnsweredEvent`` after the user answers yes/no. The full
proposal-accept / multi-option variants live in their own widgets (see
``CurationProposalCard``, ``FilePicker``, ``MultiSelectList``).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Static

from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)


class InlineConfirmCard(Widget):
    """Render a single confirmation request with yes/no buttons."""

    DEFAULT_CSS = """
    InlineConfirmCard {
        border: round #45475a;
        padding: 0 1;
        margin: 1 0;
        background: #313244;
    }
    InlineConfirmCard #confirm-question {
        padding: 0 1;
    }
    InlineConfirmCard Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        request: ConfirmationRequestedEvent,
        *,
        bus: AsyncEventBus,
    ) -> None:
        super().__init__()
        self.request = request
        self.bus = bus
        self._answered = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.request.question, id="confirm-question"),
            Horizontal(
                Button("Yes (y)", id="confirm-yes", variant="success"),
                Button("No (n)", id="confirm-no", variant="error"),
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._answered:
            return
        self._answered = True
        answer = event.button.id == "confirm-yes"
        self.bus.publish(
            ConfirmationAnsweredEvent(
                confirm_id=self.request.confirm_id,
                answer=answer,
            )
        )
        self.remove()


__all__ = ["InlineConfirmCard"]

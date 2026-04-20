"""Inline multi-select widget used for e.g. GitHub repo picking."""

from __future__ import annotations

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Static

from jobctl.core.events import (
    AsyncEventBus,
    ConfirmationAnsweredEvent,
    ConfirmationRequestedEvent,
)


class MultiSelectList(Widget):
    """Render a list of checkbox items with a confirm/cancel button row."""

    DEFAULT_CSS = """
    MultiSelectList {
        border: round #45475a;
        padding: 0 1;
        margin: 1 0;
        background: #313244;
        max-height: 24;
    }
    MultiSelectList Static.msl-heading {
        padding: 0 1;
        color: #a6adc8;
    }
    MultiSelectList Checkbox {
        padding: 0 1;
    }
    MultiSelectList VerticalScroll {
        height: 16;
    }
    MultiSelectList Button {
        margin: 0 1;
    }
    """

    class MultiSelectConfirmed(Message):
        def __init__(self, sender: Widget, selected_indices: list[int]) -> None:
            super().__init__()
            self.sender = sender
            self.selected_indices = selected_indices

    def __init__(
        self,
        request: ConfirmationRequestedEvent,
        items: Sequence[str],
        *,
        bus: AsyncEventBus,
        preselected: Sequence[int] | None = None,
    ) -> None:
        super().__init__()
        self.request = request
        self.bus = bus
        self.items = list(items)
        self._preselected = set(preselected or [])
        self._checkboxes: list[Checkbox] = []

    def compose(self) -> ComposeResult:
        yield Static(self.request.question, classes="msl-heading")
        scroll = VerticalScroll()
        yield scroll
        yield Horizontal(
            Button("Confirm", id="msl-confirm", variant="success"),
            Button("Cancel", id="msl-cancel", variant="error"),
        )

    def on_mount(self) -> None:
        scroll = self.query_one(VerticalScroll)
        for index, label in enumerate(self.items):
            checkbox = Checkbox(label, value=index in self._preselected, id=f"msl-{index}")
            self._checkboxes.append(checkbox)
            scroll.mount(checkbox)

    def _selected_indices(self) -> list[int]:
        return [index for index, cb in enumerate(self._checkboxes) if cb.value]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "msl-confirm":
            selected = self._selected_indices()
            self.post_message(self.MultiSelectConfirmed(self, selected))
            self.bus.publish(
                ConfirmationAnsweredEvent(
                    confirm_id=self.request.confirm_id,
                    answer=bool(selected),
                    payload={
                        "selected_indices": selected,
                        "selected_labels": [self.items[i] for i in selected],
                    },
                )
            )
            self.remove()
            return
        if event.button.id == "msl-cancel":
            self.bus.publish(
                ConfirmationAnsweredEvent(
                    confirm_id=self.request.confirm_id,
                    answer=False,
                )
            )
            self.remove()


__all__ = ["MultiSelectList"]

"""Live assistant message widget used while chat output streams."""

from __future__ import annotations

from rich import box
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class StreamingMessage(Static):
    """Single mutable assistant message preview."""

    DEFAULT_CSS = """
    StreamingMessage {
        padding: 0 1 0 1;
        height: auto;
        max-height: 8;
        background: transparent;
        color: #a6e3a1;
    }
    """

    def __init__(self) -> None:
        super().__init__("", id="streaming-assistant-message")
        self.content = ""

    def append(self, token: str) -> None:
        self.content += token
        self.update(
            Panel(
                Group(
                    Text("Assistant", style="bold #a6e3a1"),
                    Markdown(self.content),
                ),
                box=box.ROUNDED,
                border_style="#a6e3a1",
                style="on #1e1e2e",
                padding=(0, 1),
            )
        )


__all__ = ["StreamingMessage"]

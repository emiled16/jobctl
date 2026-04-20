"""Live assistant message widget used while chat output streams."""

from __future__ import annotations

from rich.markdown import Markdown
from textual.widgets import Static


class StreamingMessage(Static):
    """Single mutable assistant message preview."""

    DEFAULT_CSS = """
    StreamingMessage {
        border: solid #45475a;
        padding: 0 1;
        height: auto;
        max-height: 8;
        background: #1e1e2e;
        color: #cdd6f4;
    }
    """

    def __init__(self) -> None:
        super().__init__("", id="streaming-assistant-message")
        self.content = ""

    def append(self, token: str) -> None:
        self.content += token
        self.update(Markdown(f"**assistant:** {self.content}"))


__all__ = ["StreamingMessage"]

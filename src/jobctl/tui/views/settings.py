"""Settings view - read-only display of the active config."""

from __future__ import annotations

from dataclasses import asdict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Label, Static

from jobctl.config import JobctlConfig


class SettingsView(Screen):
    """Read-only summary of the project configuration."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, config: JobctlConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Label("Settings", id="settings-title")
        yield Static(self._render(), id="settings-body")

    def _render(self) -> str:
        data = asdict(self.config)
        lines: list[str] = []
        lines.append(f"provider: {self.config.llm.provider}")
        lines.append(f"chat_model: {self.config.llm.chat_model}")
        lines.append(f"embedding_model: {self.config.llm.embedding_model}")
        lines.append(f"openai.api_key_env: {self.config.llm.openai.api_key_env}")
        lines.append(f"ollama.host: {self.config.llm.ollama.host}")
        lines.append(f"ollama.embedding_model: {self.config.llm.ollama.embedding_model}")
        lines.append(f"default_template: {self.config.default_template}")
        lines.append("")
        lines.append("Run `jobctl config <dotted.key> <value>` to update.")
        lines.append(f"(Raw: {data})")
        return "\n".join(lines)

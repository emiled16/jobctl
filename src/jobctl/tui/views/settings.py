"""Settings view - read-only display of the active config."""

from __future__ import annotations

from dataclasses import asdict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static

from jobctl.config import JobctlConfig


class SettingsView(Vertical):
    """Read-only summary of the project configuration."""

    DEFAULT_CSS = """
    SettingsView { height: 1fr; padding: 1; }
    #settings-title { color: #89b4fa; text-style: bold; }
    #settings-body { padding-top: 1; }
    """

    def __init__(self, config: JobctlConfig, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.config = config

    def compose(self) -> ComposeResult:
        yield Label("Settings", id="settings-title")
        yield Static(self._render_body(), id="settings-body")

    def _render_body(self) -> str:
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

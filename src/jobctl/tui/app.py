"""Unified Textual application shell for jobctl v2."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, Static

from jobctl.config import JobctlConfig
from jobctl.core.events import AsyncEventBus
from jobctl.core.jobs.runner import BackgroundJobRunner
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.llm.base import LLMProvider
from jobctl.tui.widgets.command_palette import PaletteCommand


SCREEN_NAMES = ("chat", "graph", "tracker", "apply", "curate", "settings")


class QuitConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Confirm quit"),
            Static(self.message),
            Label("Press y to quit, n to cancel."),
            id="quit-confirm",
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class JobctlApp(App):
    """Unified jobctl shell: header, view switcher, sidebar, footer."""

    CSS = """
    Screen {
        background: #1e1e2e;
        color: #cdd6f4;
    }
    #app-header-meta {
        dock: top;
        height: 1;
        background: #313244;
        color: #cdd6f4;
        padding: 0 1;
    }
    #main-layout {
        height: 1fr;
    }
    #sidebar {
        width: 30;
        display: none;
        background: #181825;
        border-left: solid #45475a;
        padding: 1;
    }
    #sidebar.-visible {
        display: block;
    }
    DataTable {
        height: 1fr;
    }
    TextArea {
        height: 10;
    }
    """

    BINDINGS = [
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False),
        Binding("g,c", "show_chat", "Chat"),
        Binding("g,g", "show_graph", "Graph"),
        Binding("g,t", "show_tracker", "Tracker"),
        Binding("g,a", "show_apply", "Apply"),
        Binding("g,u", "show_curate", "Curate"),
        Binding("g,comma", "show_settings", "Settings"),
        Binding("colon", "open_command_palette", "Palette", show=False),
        Binding("question_mark", "open_help", "Help"),
        Binding("q", "quit_with_confirm", "Quit"),
    ]

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        project_root: Path,
        config: JobctlConfig,
        provider: LLMProvider,
        bus: AsyncEventBus | None = None,
        job_store: BackgroundJobStore | None = None,
        job_runner: BackgroundJobRunner | None = None,
        start_screen: str = "chat",
        initial_message: str | None = None,
    ) -> None:
        super().__init__()
        if start_screen not in SCREEN_NAMES:
            raise ValueError(f"Unknown start screen: {start_screen}")
        self.conn = conn
        self.project_root = project_root
        self.config = config
        self.provider = provider
        self.bus = bus or AsyncEventBus()
        self.job_store = job_store or BackgroundJobStore(conn)
        self.job_runner = job_runner or BackgroundJobRunner(self.job_store, self.bus)
        self.start_screen = start_screen
        self.session_id = uuid.uuid4().hex
        self._palette_commands: list[PaletteCommand] = []
        self.pending_chat_message: str | None = initial_message
        self._runner = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(self._header_meta(), id="app-header-meta")
        from jobctl.tui.widgets.progress_panel import ProgressPanel

        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield Label("Background jobs", id="sidebar-title")
                yield ProgressPanel(self.bus)
        yield Footer()

    def _header_meta(self) -> str:
        return (
            f"[b]{self.project_root.name}[/b]  "
            f"mode: [cyan]{self.start_screen}[/cyan]  "
            f"llm: [green]{self.config.llm.provider}[/green]/"
            f"{self.config.llm.chat_model}"
        )

    def on_mount(self) -> None:
        self.title = f"jobctl - {self.project_root}"
        self.bus.attach_loop(self._get_event_loop())
        self._install_screens()
        self._register_default_palette_commands()
        self.push_screen(self.start_screen)

    def _get_event_loop(self):
        import asyncio

        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

    def _install_screens(self) -> None:
        from jobctl.tui.views.apply import ApplyView
        from jobctl.tui.views.chat import ChatView
        from jobctl.tui.views.curate import CurateView
        from jobctl.tui.views.graph import GraphView
        from jobctl.tui.views.settings import SettingsView
        from jobctl.tui.views.tracker import TrackerView

        self.install_screen(ChatView(), name="chat")
        self.install_screen(GraphView(self.conn, provider=self.provider), name="graph")
        self.install_screen(TrackerView(self.conn), name="tracker")
        self.install_screen(ApplyView(self.conn, self.provider, self.bus), name="apply")
        self.install_screen(CurateView(self.conn, self.job_runner), name="curate")
        self.install_screen(SettingsView(self.config), name="settings")

    @property
    def agent_runner(self):
        if self._runner is None:
            from jobctl.agent.runner import LangGraphRunner

            self._runner = LangGraphRunner(
                provider=self.provider,
                conn=self.conn,
                bus=self.bus,
                session_id=self.session_id,
                store=self.job_store,
                runner=self.job_runner,
            )
        return self._runner

    def register_command(self, command: PaletteCommand) -> None:
        self._palette_commands.append(command)

    def palette_commands(self) -> list[PaletteCommand]:
        return list(self._palette_commands)

    def _register_default_palette_commands(self) -> None:
        for name in SCREEN_NAMES:
            self.register_command(
                PaletteCommand(
                    label=f"View: {name.capitalize()}",
                    description=f"Switch to the {name} view",
                    action=(lambda n=name: self.switch_screen(n)),
                )
            )
        for slash in ("/ingest resume", "/ingest github", "/curate", "/apply", "/mode"):
            self.register_command(
                PaletteCommand(
                    label=f"Slash: {slash}",
                    description=f"Send {slash} to the agent",
                    action=(lambda s=slash: self.dispatch_slash(s)),
                )
            )

    def dispatch_slash(self, command: str) -> None:
        # ChatView subscribes for slash forwarding; stash for pickup.
        self.pending_slash = command
        self.switch_screen("chat")

    def action_show_chat(self) -> None:
        self.switch_screen("chat")

    def action_show_graph(self) -> None:
        self.switch_screen("graph")

    def action_show_tracker(self) -> None:
        self.switch_screen("tracker")

    def action_show_apply(self) -> None:
        self.switch_screen("apply")

    def action_show_curate(self) -> None:
        self.switch_screen("curate")

    def action_show_settings(self) -> None:
        self.switch_screen("settings")

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("-visible")

    def action_open_command_palette(self) -> None:
        from jobctl.tui.widgets.command_palette import CommandPaletteOverlay

        self.push_screen(CommandPaletteOverlay(self.palette_commands()))

    def action_open_help(self) -> None:
        from jobctl.tui.widgets.help_overlay import KeybindingHelpOverlay

        self.push_screen(KeybindingHelpOverlay())

    def action_quit_with_confirm(self) -> None:
        active = self.job_runner.active_jobs()
        if not active:
            self.exit()
            return

        def _handle(result: bool | None) -> None:
            if result:
                self.exit()

        self.push_screen(
            QuitConfirmScreen(
                f"{len(active)} background job(s) running. Quit anyway?"
            ),
            _handle,
        )


__all__ = ["JobctlApp", "PaletteCommand"]

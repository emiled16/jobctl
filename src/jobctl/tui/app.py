"""Unified Textual application shell for jobctl v2."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Footer, Header, Label, Static

from jobctl.config import CONFIG_DIR_NAME, JobctlConfig
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

    CSS_PATH = "theme.tcss"

    BINDINGS = [
        # Priority bindings work everywhere, even while typing in an input.
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False, priority=True),
        Binding("ctrl+p", "open_command_palette", "Palette", priority=True),
        Binding("ctrl+j", "show_chat", "Chat", priority=True),
        Binding("ctrl+g", "show_graph", "Graph", priority=True),
        Binding("ctrl+t", "show_tracker", "Tracker", priority=True),
        Binding("ctrl+r", "show_apply", "Apply", priority=True),
        Binding("ctrl+e", "show_curate", "Curate", priority=True),
        Binding("ctrl+s", "show_settings", "Settings", priority=True),
        Binding("escape", "blur_focus", "Defocus", show=False, priority=True),
        Binding("ctrl+q", "quit_with_confirm", "Quit", priority=True),
        # Function-key aliases (only useful on keyboards with dedicated F-keys).
        Binding("f1", "show_chat", "Chat", show=False),
        Binding("f2", "show_graph", "Graph", show=False),
        Binding("f3", "show_tracker", "Tracker", show=False),
        Binding("f4", "show_apply", "Apply", show=False),
        Binding("f5", "show_curate", "Curate", show=False),
        Binding("f6", "show_settings", "Settings", show=False),
        # Vim-style chord bindings: only fire when no Input is focused.
        Binding("g", "start_go_chord", "Go", show=False),
        Binding("colon", "open_command_palette", "Palette", show=False),
        Binding("question_mark", "open_help", "Help"),
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
        db_path: Path | None = None,
        start_screen: str = "chat",
        initial_message: str | None = None,
    ) -> None:
        super().__init__()
        if start_screen not in SCREEN_NAMES:
            raise ValueError(f"Unknown start screen: {start_screen}")
        self.conn = conn
        self.project_root = project_root
        self.db_path = (
            db_path or _connection_path(conn) or project_root / CONFIG_DIR_NAME / "jobctl.db"
        )
        self.config = config
        self.provider = provider
        self.bus = bus or AsyncEventBus()
        self.job_store = job_store or BackgroundJobStore(conn)
        self.job_runner = job_runner or BackgroundJobRunner(
            self.job_store,
            self.bus,
            db_path=self.db_path,
        )
        self.start_screen = start_screen
        self.session_id = uuid.uuid4().hex
        self._palette_commands: list[PaletteCommand] = []
        self.pending_chat_message: str | None = initial_message
        self._runner = None
        self._current_view: str = start_screen
        self._go_chord_pending = False

    def compose(self) -> ComposeResult:
        from jobctl.tui.views.apply import ApplyView
        from jobctl.tui.views.chat import ChatView
        from jobctl.tui.views.curate import CurateView
        from jobctl.tui.views.graph import GraphView
        from jobctl.tui.views.settings import SettingsView
        from jobctl.tui.views.tracker import TrackerView
        from jobctl.tui.widgets.progress_panel import ProgressPanel

        yield Header(show_clock=False)
        yield Static(self._header_meta(), id="app-header-meta")

        with Horizontal(id="main-layout"):
            with ContentSwitcher(initial=self.start_screen, id="main-switcher"):
                yield ChatView(self.bus, id="chat")
                yield GraphView(self.conn, provider=self.provider, id="graph")
                yield TrackerView(self.conn, id="tracker")
                yield ApplyView(self.conn, self.provider, self.bus, id="apply")
                yield CurateView(self.conn, self.job_runner, id="curate")
                yield SettingsView(self.config, id="settings")
            with Vertical(id="sidebar"):
                yield Label("Background jobs", id="sidebar-title")
                yield ProgressPanel(self.bus)

        yield Footer()

    def _header_meta(self) -> str:
        return (
            f"[b]{self.project_root.name}[/b]  "
            f"mode: [cyan]{self._current_view}[/cyan]  "
            f"llm: [green]{self.config.llm.provider}[/green]/"
            f"{self.config.llm.chat_model}"
        )

    def _refresh_header_meta(self) -> None:
        try:
            self.query_one("#app-header-meta", Static).update(self._header_meta())
        except Exception:
            pass

    def on_mount(self) -> None:
        self.title = f"jobctl - {self.project_root}"
        self.bus.attach_loop(self._get_event_loop())
        self._register_default_palette_commands()
        self.show_view(self.start_screen, initial=True)

    def _get_event_loop(self):
        import asyncio

        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            return asyncio.new_event_loop()

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
                config=self.config,
                db_path=self.db_path,
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
                    action=(lambda n=name: self.show_view(n)),
                )
            )
        self.register_command(
            PaletteCommand(
                label="Workflow: Ingest resume",
                description="Choose a resume file and start ingestion",
                action=self.open_resume_ingest_input,
            )
        )
        self.register_command(
            PaletteCommand(
                label="Workflow: Ingest GitHub",
                description="Enter GitHub targets and start ingestion",
                action=self.open_github_ingest_input,
            )
        )
        self.register_command(
            PaletteCommand(
                label="Workflow: Apply",
                description="Enter a job URL or description and start apply",
                action=self.open_apply_input,
            )
        )
        self.register_command(
            PaletteCommand(
                label="Workflow: Curate",
                description="Switch to the Curate view",
                action=lambda: self.show_view("curate"),
            )
        )
        self.register_command(
            PaletteCommand(
                label="Slash: /mode",
                description="Show or change the agent mode",
                action=lambda: self.dispatch_slash("/mode"),
            )
        )

    def show_view(self, name: str, *, initial: bool = False) -> None:
        """Switch the main content area to a named app view."""
        if name not in SCREEN_NAMES:
            raise ValueError(f"Unknown view: {name}")
        switcher = self.query_one("#main-switcher", ContentSwitcher)
        if switcher.current != name:
            switcher.current = name
        self._current_view = name
        self._refresh_header_meta()
        if name == "chat":
            self._focus_chat_input()
            if initial:
                self._handle_initial_chat_message()

    def _show_view(self, name: str, *, initial: bool = False) -> None:
        self.show_view(name, initial=initial)

    def _focus_chat_input(self) -> None:
        try:
            from textual.widgets import Input

            self.query_one("#chat-input", Input).focus()
        except Exception:
            pass

    def _handle_initial_chat_message(self) -> None:
        if not self.pending_chat_message:
            return
        from jobctl.tui.views.chat import ChatView

        try:
            chat = self.query_one(ChatView)
        except Exception:
            return
        message = self.pending_chat_message
        self.pending_chat_message = None
        chat._handle_submission(str(message))

    def on_key(self, event: events.Key) -> None:
        if self.focused is not None or not self._go_chord_pending:
            return
        self._go_chord_pending = False
        target_by_key = {
            "c": "chat",
            "g": "graph",
            "t": "tracker",
            "a": "apply",
            "u": "curate",
            "comma": "settings",
        }
        target = target_by_key.get(event.key)
        if target is None:
            return
        event.stop()
        self.show_view(target)

    def dispatch_slash(self, command: str) -> None:
        self.pending_slash = command
        self.show_view("chat")
        from jobctl.tui.views.chat import ChatView

        try:
            chat = self.query_one(ChatView)
            chat._handle_pending_slash_if_any()
        except Exception:
            pass

    def _with_chat_view(self, callback_name: str) -> None:
        self.show_view("chat")
        from jobctl.tui.views.chat import ChatView

        try:
            chat = self.query_one(ChatView)
            getattr(chat, callback_name)()
        except Exception:
            pass

    def open_resume_ingest_input(self) -> None:
        self._with_chat_view("open_resume_picker")

    def open_github_ingest_input(self) -> None:
        self._with_chat_view("open_github_ingest_input")

    def open_apply_input(self) -> None:
        self._with_chat_view("open_apply_input")

    def action_show_chat(self) -> None:
        self.show_view("chat")

    def action_show_graph(self) -> None:
        self.show_view("graph")

    def action_show_tracker(self) -> None:
        self.show_view("tracker")

    def action_show_apply(self) -> None:
        self.show_view("apply")

    def action_show_curate(self) -> None:
        self.show_view("curate")

    def action_show_settings(self) -> None:
        self.show_view("settings")

    def action_start_go_chord(self) -> None:
        if self.focused is None:
            self._go_chord_pending = True

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("-visible")

    def action_blur_focus(self) -> None:
        focused = self.focused
        if focused is not None:
            self.set_focus(None)

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
            QuitConfirmScreen(f"{len(active)} background job(s) running. Quit anyway?"),
            _handle,
        )


__all__ = ["JobctlApp", "PaletteCommand"]


def _connection_path(conn: sqlite3.Connection) -> Path | None:
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    path = row["file"] if isinstance(row, sqlite3.Row) else row[2]
    return Path(path) if path else None

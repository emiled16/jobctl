"""Textual application root."""

import sqlite3
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from jobctl.tui.profile_view import ProfileScreen
from jobctl.tui.tracker_view import TrackerScreen


class JobctlApp(App):
    """Textual shell for jobctl tracker and profile screens."""

    CSS = """
    Screen {
        background: #1e1e2e;
        color: #cdd6f4;
    }
    DataTable {
        height: 1fr;
    }
    TextArea {
        height: 10;
    }
    """
    BINDINGS = [
        Binding("t", "show_tracker", "Tracker"),
        Binding("p", "show_profile", "Profile"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        conn: sqlite3.Connection,
        project_root: Path,
        start_screen: str = "tracker",
        llm_client=None,
    ) -> None:
        super().__init__()
        self.conn = conn
        self.project_root = project_root
        self.start_screen = start_screen
        self.llm_client = llm_client

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"jobctl - {self.project_root}"
        self.install_screen(TrackerScreen(self.conn), name="tracker")
        self.install_screen(ProfileScreen(self.conn, llm_client=self.llm_client), name="profile")
        self.push_screen(self.start_screen)

    def action_show_tracker(self) -> None:
        self.switch_screen("tracker")

    def action_show_profile(self) -> None:
        self.switch_screen("profile")

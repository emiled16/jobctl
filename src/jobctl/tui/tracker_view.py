"""Job tracker TUI view."""

import sqlite3

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Label, Select, Static, TextArea

from jobctl.jobs.tracker import (
    ALLOWED_STATUSES,
    get_application,
    list_applications,
    update_application,
)


class TrackerScreen(Screen):
    """Application tracker table and detail view."""

    BINDINGS = [
        Binding("enter", "show_selected", "Details"),
        Binding("n", "focus_notes", "Notes"),
        Binding("s", "status_next", "Status"),
    ]

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.current_app_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Applications"),
            Select(
                [
                    ("All", "all"),
                    *[(status.title(), status) for status in sorted(ALLOWED_STATUSES)],
                ],
                id="status-filter",
                value="all",
            ),
            Horizontal(
                DataTable(id="applications"),
                Vertical(
                    Static("Select an application and press Enter.", id="detail"),
                    TextArea(id="notes"),
                ),
            ),
        )

    def on_mount(self) -> None:
        table = self.query_one("#applications", DataTable)
        table.cursor_type = "row"
        table.add_columns("Company", "Role", "Status", "Score", "Date", "Location", "Follow-up")
        self._populate_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "status-filter":
            self._populate_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.current_app_id = str(event.row_key.value)
        self._show_application(self.current_app_id)

    def action_show_selected(self) -> None:
        table = self.query_one("#applications", DataTable)
        if table.cursor_row < 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self.current_app_id = str(row_key.value)
        self._show_application(self.current_app_id)

    def action_focus_notes(self) -> None:
        self.query_one("#notes", TextArea).focus()

    def action_status_next(self) -> None:
        if self.current_app_id is None:
            return
        statuses = ["evaluated", "materials_ready", "applied", "interviewing", "offer", "rejected"]
        application = get_application(self.conn, self.current_app_id)
        current_index = (
            statuses.index(application["status"]) if application["status"] in statuses else 0
        )
        new_status = statuses[(current_index + 1) % len(statuses)]
        update_application(self.conn, self.current_app_id, status=new_status)
        self._populate_table()
        self._show_application(self.current_app_id)

    def on_blur(self, event) -> None:
        if (
            isinstance(event.sender, TextArea)
            and event.sender.id == "notes"
            and self.current_app_id is not None
        ):
            update_application(self.conn, self.current_app_id, notes=event.sender.text)

    def _populate_table(self) -> None:
        table = self.query_one("#applications", DataTable)
        table.clear()
        status_filter = self.query_one("#status-filter", Select).value
        applications = list_applications(
            self.conn,
            status_filter=None if status_filter == "all" else str(status_filter),
        )
        for application in applications:
            status = str(application["status"])
            table.add_row(
                application["company"],
                application["role"],
                _status_text(status),
                "" if application["fit_score"] is None else f"{application['fit_score']:.1f}",
                application["created_at"][:10],
                application["location"] or "",
                application["follow_up_date"] or "",
                key=application["id"],
            )

    def _show_application(self, app_id: str) -> None:
        application = get_application(self.conn, app_id)
        events = "\n".join(
            f"- {event['created_at'][:19]} {event['event_type']}: {event['description'] or ''}"
            for event in application["events"]
        )
        detail = (
            f"{application['role']} at {application['company']}\n"
            f"Status: {application['status']} | Score: {application['fit_score']}\n"
            f"Resume YAML: {application['resume_yaml_path'] or ''}\n"
            f"Resume PDF: {application['resume_pdf_path'] or ''}\n"
            f"Cover YAML: {application['cover_letter_yaml_path'] or ''}\n"
            f"Cover PDF: {application['cover_letter_pdf_path'] or ''}\n\n"
            f"JD:\n{application['jd_raw'] or ''}\n\n"
            f"Timeline:\n{events}"
        )
        self.query_one("#detail", Static).update(detail)
        self.query_one("#notes", TextArea).text = application["notes"] or ""


def _status_text(status: str) -> Text:
    colors = {
        "offer": "green",
        "interviewing": "yellow",
        "applied": "grey70",
        "rejected": "red",
        "materials_ready": "blue",
    }
    return Text(status, style=colors.get(status, "white"))

"""Application tracker view (ported and extended from v1 TrackerScreen)."""

from __future__ import annotations

import subprocess
import sys
import sqlite3
import uuid
from datetime import date
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Input, Label, Select, Static, TextArea

from datetime import datetime, timezone

from jobctl.jobs.tracker import (
    ALLOWED_STATUSES,
    get_application,
    list_applications,
    update_application,
)


STATUS_CYCLE = [
    "evaluated",
    "materials_ready",
    "applied",
    "interviewing",
    "offer",
    "rejected",
]


class InlineApplyForm(ModalScreen[dict[str, Any] | None]):
    """Compact form for creating a new application record."""

    DEFAULT_CSS = """
    InlineApplyForm {
        align: center middle;
    }
    #inline-form {
        width: 80;
        background: #181825;
        border: solid #45475a;
        padding: 1 2;
    }
    #inline-form Input, #inline-form TextArea {
        margin: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("New application"),
            Input(placeholder="Company", id="apply-company"),
            Input(placeholder="Role", id="apply-role"),
            Input(placeholder="Job URL (optional)", id="apply-url"),
            TextArea(id="apply-jd"),
            Horizontal(
                Button("Save", id="apply-save", variant="primary"),
                Button("Cancel", id="apply-cancel"),
            ),
            id="inline-form",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-save":
            payload = {
                "company": self.query_one("#apply-company", Input).value.strip(),
                "role": self.query_one("#apply-role", Input).value.strip(),
                "url": self.query_one("#apply-url", Input).value.strip() or None,
                "jd_raw": self.query_one("#apply-jd", TextArea).text,
            }
            if not payload["company"] or not payload["role"]:
                return
            self.dismiss(payload)
        else:
            self.dismiss(None)


class TrackerView(Screen):
    """Applications DataTable with inline new-application form and follow-up colouring."""

    BINDINGS = [
        Binding("enter", "show_selected", "Details"),
        Binding("n", "focus_notes", "Notes"),
        Binding("s", "status_next", "Status"),
        Binding("a", "new_application", "New"),
        Binding("o", "open_pdf", "Open PDF"),
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
                id="tracker-filter",
                value="all",
                allow_blank=False,
            ),
            Horizontal(
                DataTable(id="tracker-table"),
                Vertical(
                    Static("Select an application and press Enter.", id="tracker-detail"),
                    TextArea(id="tracker-notes"),
                ),
            ),
        )

    def on_mount(self) -> None:
        table = self.query_one("#tracker-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "Company", "Role", "Status", "Score", "Date", "Location", "Follow-up"
        )
        self._populate_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "tracker-filter":
            self._populate_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.current_app_id = str(event.row_key.value)
        self._show_application(self.current_app_id)

    def action_show_selected(self) -> None:
        table = self.query_one("#tracker-table", DataTable)
        if table.cursor_row < 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        self.current_app_id = str(row_key.value)
        self._show_application(self.current_app_id)

    def action_focus_notes(self) -> None:
        self.query_one("#tracker-notes", TextArea).focus()

    def action_status_next(self) -> None:
        if self.current_app_id is None:
            return
        application = get_application(self.conn, self.current_app_id)
        current_index = (
            STATUS_CYCLE.index(application["status"]) if application["status"] in STATUS_CYCLE else 0
        )
        new_status = STATUS_CYCLE[(current_index + 1) % len(STATUS_CYCLE)]
        update_application(self.conn, self.current_app_id, status=new_status)
        self._populate_table()
        self._show_application(self.current_app_id)

    def action_new_application(self) -> None:
        def _handle(payload: dict[str, Any] | None) -> None:
            if payload is None:
                return
            app_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO applications
                        (id, company, role, url, status, jd_raw, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'evaluated', ?, ?, ?)
                    """,
                    (
                        app_id,
                        payload["company"],
                        payload["role"],
                        payload["url"],
                        payload["jd_raw"] or None,
                        now,
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO application_events
                        (id, application_id, event_type, description, created_at)
                    VALUES (?, ?, 'created', ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        app_id,
                        f"Created application for {payload['role']} at {payload['company']}",
                        now,
                    ),
                )
            self._populate_table()

        self.app.push_screen(InlineApplyForm(), _handle)

    def action_open_pdf(self) -> None:
        if self.current_app_id is None:
            return
        application = get_application(self.conn, self.current_app_id)
        pdf_path = application.get("resume_pdf_path") if application else None
        if not pdf_path:
            self.query_one("#tracker-detail", Static).update("No resume PDF recorded.")
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", pdf_path])
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", pdf_path])
            elif sys.platform == "win32":
                subprocess.Popen(["start", "", pdf_path], shell=True)
        except Exception as exc:
            self.query_one("#tracker-detail", Static).update(f"Open failed: {exc}")

    def on_blur(self, event) -> None:
        sender = getattr(event, "sender", None)
        if (
            isinstance(sender, TextArea)
            and sender.id == "tracker-notes"
            and self.current_app_id is not None
        ):
            update_application(self.conn, self.current_app_id, notes=sender.text)

    def _populate_table(self) -> None:
        table = self.query_one("#tracker-table", DataTable)
        table.clear()
        status_filter = self.query_one("#tracker-filter", Select).value
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
                _follow_up_text(application["follow_up_date"]),
                key=application["id"],
            )

    def _show_application(self, app_id: str) -> None:
        application = get_application(self.conn, app_id)
        events = "\n".join(
            f"- {event['created_at'][:19]} {event['event_type']}: "
            f"{event['description'] or ''}"
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
        self.query_one("#tracker-detail", Static).update(detail)
        self.query_one("#tracker-notes", TextArea).text = application["notes"] or ""


def _status_text(status: str) -> Text:
    colors = {
        "offer": "green",
        "interviewing": "yellow",
        "applied": "grey70",
        "rejected": "red",
        "materials_ready": "blue",
    }
    return Text(status, style=colors.get(status, "white"))


def _follow_up_text(raw: str | None) -> Text:
    if not raw:
        return Text("")
    try:
        follow_up = date.fromisoformat(raw[:10])
    except ValueError:
        return Text(raw)
    today = date.today()
    style = "white"
    if follow_up < today:
        style = "red"
    elif (follow_up - today).days <= 3:
        style = "yellow"
    return Text(raw[:10], style=style)

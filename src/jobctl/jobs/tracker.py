"""Job tracker CRUD operations."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from jobctl.llm.schemas import ExtractedJD, FitEvaluation


Application = dict[str, Any]
ApplicationEvent = dict[str, Any]

ALLOWED_STATUSES = {
    "evaluated",
    "materials_ready",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
}

APPLICATION_FIELDS = {
    "company",
    "role",
    "url",
    "status",
    "fit_score",
    "location",
    "compensation",
    "jd_raw",
    "jd_structured",
    "evaluation_structured",
    "resume_yaml_path",
    "cover_letter_yaml_path",
    "resume_pdf_path",
    "cover_letter_pdf_path",
    "notes",
    "recruiter_name",
    "recruiter_email",
    "recruiter_linkedin",
    "follow_up_date",
}
SORT_FIELDS = {"created_at", "updated_at", "company", "role", "status", "fit_score"}


def create_application(
    conn: sqlite3.Connection,
    company: str,
    role: str,
    url: str | None,
    jd: ExtractedJD,
    evaluation: FitEvaluation,
) -> str:
    """Create an evaluated application tracker entry."""
    app_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO applications (
            id, company, role, url, status, fit_score, location, compensation, jd_raw,
            jd_structured, evaluation_structured, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            app_id,
            company,
            role,
            url,
            "evaluated",
            evaluation.score,
            jd.location,
            jd.compensation,
            jd.raw_text,
            jd.model_dump_json(),
            evaluation.model_dump_json(),
            now,
            now,
        ),
    )
    _insert_event(conn, app_id, "created", f"Created application for {role} at {company}")
    conn.commit()
    return app_id


def update_status(conn: sqlite3.Connection, app_id: str, new_status: str) -> None:
    """Update application status and record a timeline event."""
    if new_status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid application status: {new_status}")

    _ensure_application_exists(conn, app_id)
    conn.execute(
        "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, _utc_now(), app_id),
    )
    _insert_event(conn, app_id, "status_changed", f"Status changed to {new_status}")
    conn.commit()


def update_application(conn: sqlite3.Connection, app_id: str, **kwargs: Any) -> None:
    """Update editable application fields and record a timeline event."""
    unknown_fields = set(kwargs) - APPLICATION_FIELDS
    if unknown_fields:
        joined_fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unknown application field(s): {joined_fields}")
    if not kwargs:
        return
    if "status" in kwargs and kwargs["status"] not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid application status: {kwargs['status']}")

    _ensure_application_exists(conn, app_id)
    updates = [f"{field} = ?" for field in kwargs]
    values = [_serialize_field(field, value) for field, value in kwargs.items()]
    updates.append("updated_at = ?")
    values.append(_utc_now())
    values.append(app_id)
    conn.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id = ?", values)

    event_type = "note_added" if set(kwargs) == {"notes"} else "application_updated"
    if any(field.endswith("_path") for field in kwargs):
        event_type = "materials_generated"
    if "status" in kwargs:
        event_type = "status_changed"
    _insert_event(conn, app_id, event_type, f"Updated {', '.join(kwargs)}")
    conn.commit()


def get_application(conn: sqlite3.Connection, app_id: str) -> Application:
    """Return an application row with its timeline events."""
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise KeyError(f"Application not found: {app_id}")
    application = _application_from_row(row)
    application["events"] = get_timeline(conn, app_id)
    return application


def list_applications(
    conn: sqlite3.Connection,
    status_filter: str | None = None,
    sort_by: str = "created_at",
) -> list[Application]:
    """List applications with optional status filtering."""
    if sort_by not in SORT_FIELDS:
        raise ValueError(f"Unsupported sort field: {sort_by}")
    if status_filter is not None and status_filter not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid application status: {status_filter}")

    if status_filter is None:
        rows = conn.execute(f"SELECT * FROM applications ORDER BY {sort_by} DESC").fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM applications WHERE status = ? ORDER BY {sort_by} DESC",
            (status_filter,),
        ).fetchall()
    return [_application_from_row(row) for row in rows]


def get_timeline(conn: sqlite3.Connection, app_id: str) -> list[ApplicationEvent]:
    """Return timeline events for an application in chronological order."""
    _ensure_application_exists(conn, app_id)
    rows = conn.execute(
        """
        SELECT *
        FROM application_events
        WHERE application_id = ?
        ORDER BY created_at, id
        """,
        (app_id,),
    ).fetchall()
    return [_event_from_row(row) for row in rows]


def _insert_event(
    conn: sqlite3.Connection,
    app_id: str,
    event_type: str,
    description: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO application_events (id, application_id, event_type, description, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), app_id, event_type, description, _utc_now()),
    )


def _ensure_application_exists(conn: sqlite3.Connection, app_id: str) -> None:
    row = conn.execute("SELECT 1 FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise KeyError(f"Application not found: {app_id}")


def _application_from_row(row: sqlite3.Row) -> Application:
    application = dict(row)
    for field in ("jd_structured", "evaluation_structured"):
        if application.get(field):
            application[field] = json.loads(application[field])
    return application


def _event_from_row(row: sqlite3.Row) -> ApplicationEvent:
    return dict(row)


def _serialize_field(field: str, value: Any) -> Any:
    if field in {"jd_structured", "evaluation_structured"} and not isinstance(value, str):
        return json.dumps(value, sort_keys=True)
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

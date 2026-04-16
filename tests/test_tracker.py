import sqlite3
from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.jobs.tracker import (
    create_application,
    get_application,
    get_timeline,
    list_applications,
    update_application,
    update_status,
)
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_create_application_and_retrieve_fields(conn: sqlite3.Connection) -> None:
    app_id = create_application(
        conn, "Acme", "Senior Engineer", "https://example.com", make_jd(), make_eval()
    )

    application = get_application(conn, app_id)

    assert application["company"] == "Acme"
    assert application["role"] == "Senior Engineer"
    assert application["status"] == "evaluated"
    assert application["fit_score"] == 8.0
    assert application["jd_structured"]["title"] == "Senior Engineer"
    assert application["events"][0]["event_type"] == "created"


def test_update_status_validates_values(conn: sqlite3.Connection) -> None:
    app_id = create_application(conn, "Acme", "Senior Engineer", None, make_jd(), make_eval())

    update_status(conn, app_id, "applied")

    assert get_application(conn, app_id)["status"] == "applied"
    with pytest.raises(ValueError):
        update_status(conn, app_id, "bad")


def test_update_application_and_timeline(conn: sqlite3.Connection) -> None:
    app_id = create_application(conn, "Acme", "Senior Engineer", None, make_jd(), make_eval())

    update_application(conn, app_id, notes="Follow up Friday", resume_pdf_path="/tmp/resume.pdf")

    application = get_application(conn, app_id)
    timeline = get_timeline(conn, app_id)
    assert application["notes"] == "Follow up Friday"
    assert timeline[-1]["event_type"] == "materials_generated"


def test_list_applications_filters_by_status(conn: sqlite3.Connection) -> None:
    first_id = create_application(conn, "Acme", "Senior Engineer", None, make_jd(), make_eval())
    create_application(conn, "Beta", "Staff Engineer", None, make_jd(), make_eval())
    update_status(conn, first_id, "applied")

    all_apps = list_applications(conn)
    applied_apps = list_applications(conn, status_filter="applied")

    assert len(all_apps) == 2
    assert [app["id"] for app in applied_apps] == [first_id]


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build systems"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="Raw JD",
    )


def make_eval() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Python"],
        gaps=[],
        recommendations=["Lead with Python"],
        summary="Strong fit.",
    )

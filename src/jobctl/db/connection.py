"""SQLite connection management and migrations."""

import sqlite3
from collections.abc import Callable
from pathlib import Path


Migration = tuple[str, Callable[[sqlite3.Connection], None]]


def get_connection(db_path: Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _run_migrations(conn)
    from jobctl.db.vectors import init_vec

    init_vec(conn)
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied_migrations = {
        row["name"] for row in conn.execute("SELECT name FROM _migrations").fetchall()
    }

    for name, migration in MIGRATIONS:
        if name in applied_migrations:
            continue
        with conn:
            migration(conn)
            conn.execute("INSERT INTO _migrations (name) VALUES (?)", (name,))


def _migration_001_create_graph_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            properties TEXT,
            text_representation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_nodes_type ON nodes (type)")
    conn.execute(
        """
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_edges_source_id ON edges (source_id)")
    conn.execute("CREATE INDEX idx_edges_target_id ON edges (target_id)")
    conn.execute("CREATE INDEX idx_edges_relation ON edges (relation)")


def _migration_002_create_tracker_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE applications (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            url TEXT,
            status TEXT NOT NULL DEFAULT 'evaluated',
            fit_score REAL,
            location TEXT,
            compensation TEXT,
            jd_raw TEXT,
            jd_structured TEXT,
            evaluation_structured TEXT,
            resume_yaml_path TEXT,
            cover_letter_yaml_path TEXT,
            resume_pdf_path TEXT,
            cover_letter_pdf_path TEXT,
            notes TEXT,
            recruiter_name TEXT,
            recruiter_email TEXT,
            recruiter_linkedin TEXT,
            follow_up_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_applications_status ON applications (status)")
    conn.execute("CREATE INDEX idx_applications_company ON applications (company)")
    conn.execute(
        """
        CREATE TABLE application_events (
            id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_application_events_application_id ON application_events (application_id)"
    )


MIGRATIONS: list[Migration] = [
    ("001_create_graph_tables", _migration_001_create_graph_tables),
    ("002_create_tracker_tables", _migration_002_create_tracker_tables),
]

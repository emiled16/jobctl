"""SQLite connection management and migrations."""

import sqlite3
from collections.abc import Callable
from pathlib import Path


Migration = tuple[str, Callable[[sqlite3.Connection], None]]


def get_connection(db_path: Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # LangGraph may run sync nodes in worker threads. We allow this connection
    # to be used across threads and rely on SQLite's own serialized access.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
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


def _migration_003_create_ingestion_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE ingestion_jobs (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued',
            cursor TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_ingestion_jobs_source ON ingestion_jobs (source_type, source_key)"
    )
    conn.execute("CREATE INDEX idx_ingestion_jobs_state ON ingestion_jobs (state)")
    conn.execute(
        """
        CREATE TABLE ingested_items (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
            external_id TEXT NOT NULL,
            external_updated_at TEXT,
            node_id TEXT,
            status TEXT NOT NULL DEFAULT 'done',
            error TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_ingested_items_job ON ingested_items (job_id)")
    conn.execute(
        "CREATE UNIQUE INDEX idx_ingested_items_external ON ingested_items (job_id, external_id)"
    )


def _migration_004_create_node_sources(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE node_sources (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_ref TEXT,
            confidence REAL,
            source_quote TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX idx_node_sources_node ON node_sources (node_id)")
    conn.execute("CREATE INDEX idx_node_sources_type ON node_sources (source_type)")


def _migration_005_create_agent_sessions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE agent_sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            state_json TEXT NOT NULL
        )
        """
    )


def _migration_006_create_curation_proposals(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE curation_proposals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            decided_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_curation_proposals_status ON curation_proposals (status)")
    conn.execute("CREATE INDEX idx_curation_proposals_kind ON curation_proposals (kind)")


def _migration_007_create_embedding_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE embedding_meta (
            node_id TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
            embedding_model TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _migration_008_create_refinement_questions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE refinement_questions (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_ref TEXT,
            target_node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
            fact_json TEXT,
            category TEXT NOT NULL,
            prompt TEXT NOT NULL,
            options_json TEXT NOT NULL,
            allow_free_text INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            answer_text TEXT,
            answer_json TEXT,
            priority INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            answered_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_refinement_questions_status ON refinement_questions (status)")
    conn.execute(
        "CREATE INDEX idx_refinement_questions_target ON refinement_questions (target_node_id)"
    )
    conn.execute(
        "CREATE INDEX idx_refinement_questions_source ON refinement_questions (source_type, source_ref)"
    )


MIGRATIONS: list[Migration] = [
    ("001_create_graph_tables", _migration_001_create_graph_tables),
    ("002_create_tracker_tables", _migration_002_create_tracker_tables),
    ("003_create_ingestion_tables", _migration_003_create_ingestion_tables),
    ("004_create_node_sources", _migration_004_create_node_sources),
    ("005_create_agent_sessions", _migration_005_create_agent_sessions),
    ("006_create_curation_proposals", _migration_006_create_curation_proposals),
    ("007_create_embedding_meta", _migration_007_create_embedding_meta),
    ("008_create_refinement_questions", _migration_008_create_refinement_questions),
]

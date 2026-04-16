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


MIGRATIONS: list[Migration] = [
    ("001_create_graph_tables", _migration_001_create_graph_tables),
]

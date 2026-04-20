"""Persistent store for background ingestion jobs and their processed items."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

JOB_STATES = ("queued", "running", "failed", "done")


@dataclass(frozen=True)
class JobRecord:
    id: str
    source_type: str
    source_key: str
    state: str
    cursor: dict[str, Any]
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class ItemRecord:
    id: str
    job_id: str
    external_id: str
    external_updated_at: str | None
    node_id: str | None
    status: str
    error: str | None
    created_at: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, default=str)


def _row_to_job(row: sqlite3.Row | None) -> JobRecord | None:
    if row is None:
        return None
    raw_cursor = row["cursor"]
    cursor: dict[str, Any] = {}
    if raw_cursor:
        try:
            parsed = json.loads(raw_cursor)
            if isinstance(parsed, dict):
                cursor = parsed
        except json.JSONDecodeError:
            cursor = {"_raw": raw_cursor}
    return JobRecord(
        id=row["id"],
        source_type=row["source_type"],
        source_key=row["source_key"],
        state=row["state"],
        cursor=cursor,
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def _row_to_item(row: sqlite3.Row) -> ItemRecord:
    return ItemRecord(
        id=row["id"],
        job_id=row["job_id"],
        external_id=row["external_id"],
        external_updated_at=row["external_updated_at"],
        node_id=row["node_id"],
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
    )


class BackgroundJobStore:
    """CRUD for ``ingestion_jobs`` and ``ingested_items`` tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_job(
        self,
        source_type: str,
        source_key: str,
        *,
        cursor: dict[str, Any] | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO ingestion_jobs
                    (id, source_type, source_key, state, cursor, error,
                     created_at, updated_at, completed_at)
                VALUES (?, ?, ?, 'queued', ?, NULL, ?, ?, NULL)
                """,
                (
                    job_id,
                    source_type,
                    source_key,
                    _dumps(cursor or {}),
                    now,
                    now,
                ),
            )
        return job_id

    def update_job(
        self,
        job_id: str,
        *,
        state: str | None = None,
        cursor: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if state is not None and state not in JOB_STATES:
            raise ValueError(f"invalid job state: {state}")

        sets: list[str] = ["updated_at = ?"]
        values: list[Any] = [_utcnow()]

        if state is not None:
            sets.append("state = ?")
            values.append(state)
            if state == "done" or state == "failed":
                sets.append("completed_at = ?")
                values.append(_utcnow())
        if cursor is not None:
            sets.append("cursor = ?")
            values.append(_dumps(cursor))
        if error is not None:
            sets.append("error = ?")
            values.append(error)

        values.append(job_id)
        with self._conn:
            self._conn.execute(
                f"UPDATE ingestion_jobs SET {', '.join(sets)} WHERE id = ?",
                values,
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        row = self._conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row)

    def find_pending_job(
        self,
        source_type: str,
        source_key: str,
    ) -> JobRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM ingestion_jobs
            WHERE source_type = ? AND source_key = ? AND state IN ('queued', 'running', 'failed')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (source_type, source_key),
        ).fetchone()
        return _row_to_job(row)

    def list_jobs(self, *, limit: int = 50) -> list[JobRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ingestion_jobs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r for r in (_row_to_job(row) for row in rows) if r is not None]

    def mark_item_done(
        self,
        job_id: str,
        external_id: str,
        *,
        external_updated_at: str | None = None,
        node_id: str | None = None,
        status: str = "done",
        error: str | None = None,
    ) -> str:
        item_id = uuid.uuid4().hex
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO ingested_items
                    (id, job_id, external_id, external_updated_at, node_id,
                     status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, external_id) DO UPDATE SET
                    external_updated_at = excluded.external_updated_at,
                    node_id = excluded.node_id,
                    status = excluded.status,
                    error = excluded.error
                """,
                (
                    item_id,
                    job_id,
                    external_id,
                    external_updated_at,
                    node_id,
                    status,
                    error,
                    now,
                ),
            )
        return item_id

    def is_item_seen(
        self,
        job_id: str,
        external_id: str,
        external_updated_at: str | None = None,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT external_updated_at FROM ingested_items
            WHERE job_id = ? AND external_id = ? AND status = 'done'
            """,
            (job_id, external_id),
        ).fetchone()
        if row is None:
            return False
        if external_updated_at is None:
            return True
        stored = row["external_updated_at"]
        if stored is None:
            return True
        return stored >= external_updated_at

    def list_items(self, job_id: str) -> list[ItemRecord]:
        rows = self._conn.execute(
            "SELECT * FROM ingested_items WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        ).fetchall()
        return [_row_to_item(row) for row in rows]


__all__ = ["BackgroundJobStore", "JobRecord", "ItemRecord", "JOB_STATES"]

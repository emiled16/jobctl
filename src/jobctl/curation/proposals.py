"""CRUD for the ``curation_proposals`` table.

A :class:`Proposal` represents an agent-generated suggestion that the user
can accept, reject, or edit. The ``payload`` dict is kind-specific:

* ``merge``: ``{"node_a_id", "node_b_id", "merged_name", "merged_text"}``
* ``prune``: ``{"node_id", "reason"}``
* ``connect``: ``{"source_id", "target_id", "relation"}``
* ``rephrase``: ``{"node_id", "original_text", "proposed_text"}``
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ProposalKind = Literal["merge", "prune", "connect", "rephrase"]
ProposalStatus = Literal["pending", "accepted", "rejected", "edited"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Proposal:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = ""
    decided_at: str | None = None


class CurationProposalStore:
    """Lightweight CRUD over ``curation_proposals``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_proposal(self, kind: ProposalKind, payload: dict[str, Any]) -> str:
        proposal_id = uuid.uuid4().hex
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO curation_proposals
                    (id, kind, payload_json, status, created_at, decided_at)
                VALUES (?, ?, ?, 'pending', ?, NULL)
                """,
                (proposal_id, kind, json.dumps(payload), now),
            )
        return proposal_id

    def get(self, proposal_id: str) -> Proposal | None:
        row = self._conn.execute(
            """
            SELECT id, kind, payload_json, status, created_at, decided_at
            FROM curation_proposals
            WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()
        return _row_to_proposal(row) if row else None

    def list_pending(self, kind: str | None = None) -> list[Proposal]:
        if kind is None:
            rows = self._conn.execute(
                """
                SELECT id, kind, payload_json, status, created_at, decided_at
                FROM curation_proposals
                WHERE status = 'pending'
                ORDER BY created_at DESC
                """
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, kind, payload_json, status, created_at, decided_at
                FROM curation_proposals
                WHERE status = 'pending' AND kind = ?
                ORDER BY created_at DESC
                """,
                (kind,),
            ).fetchall()
        return [_row_to_proposal(row) for row in rows]

    def accept(self, proposal_id: str) -> None:
        self._set_status(proposal_id, "accepted")

    def reject(self, proposal_id: str) -> None:
        self._set_status(proposal_id, "rejected")

    def mark_edited(self, proposal_id: str, edited_payload: dict[str, Any]) -> None:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE curation_proposals
                SET payload_json = ?, status = 'edited', decided_at = ?
                WHERE id = ?
                """,
                (json.dumps(edited_payload), now, proposal_id),
            )

    def _set_status(self, proposal_id: str, status: ProposalStatus) -> None:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE curation_proposals
                SET status = ?, decided_at = ?
                WHERE id = ?
                """,
                (status, now, proposal_id),
            )


def _row_to_proposal(row: Any) -> Proposal:
    return Proposal(
        id=row[0],
        kind=row[1],
        payload=json.loads(row[2]) if row[2] else {},
        status=row[3],
        created_at=row[4],
        decided_at=row[5],
    )


__all__ = ["CurationProposalStore", "Proposal", "ProposalKind", "ProposalStatus"]

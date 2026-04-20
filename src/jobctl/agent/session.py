"""Persistence helpers for ``AgentState`` using the ``agent_sessions`` table."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from jobctl.agent.state import AgentState, new_state


_PERSISTED_KEYS = (
    "messages",
    "mode",
    "pending_confirmation",
    "coverage",
    "last_tool_result",
    "session_id",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_session(conn: sqlite3.Connection, state: AgentState) -> None:
    """Upsert ``state`` into the ``agent_sessions`` table."""
    session_id = state.get("session_id")
    if not session_id:
        raise ValueError("AgentState is missing session_id")

    payload = {key: state.get(key) for key in _PERSISTED_KEYS}
    state_json = json.dumps(payload, default=str)
    now = _now_iso()

    conn.execute(
        """
        INSERT INTO agent_sessions (id, created_at, updated_at, state_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            updated_at = excluded.updated_at,
            state_json = excluded.state_json
        """,
        (session_id, now, now, state_json),
    )
    conn.commit()


def load_session(conn: sqlite3.Connection, session_id: str) -> AgentState | None:
    """Return the persisted ``AgentState`` for ``session_id`` if any."""
    row = conn.execute(
        "SELECT state_json FROM agent_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["state_json"])
    except (TypeError, json.JSONDecodeError):
        return None

    state = new_state(session_id=session_id)
    for key in _PERSISTED_KEYS:
        if key in payload and payload[key] is not None:
            state[key] = payload[key]  # type: ignore[typeddict-unknown-key]
    state["session_id"] = session_id
    return state


def list_recent_sessions(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
) -> list[tuple[str, str]]:
    """Return ``(session_id, updated_at)`` for the most recent sessions."""
    rows = conn.execute(
        "SELECT id, updated_at FROM agent_sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(row["id"], row["updated_at"]) for row in rows]


__all__ = ["list_recent_sessions", "load_session", "save_session"]

"""Apply accepted curation proposal payloads to the graph."""

from __future__ import annotations

import sqlite3
from typing import Any

from jobctl.db.graph import (
    add_edge,
    delete_node,
    get_edges_from,
    get_edges_to,
    get_node,
    update_node,
)


def apply_proposal(conn: sqlite3.Connection, kind: str, payload: dict[str, Any]) -> None:
    if kind == "merge":
        apply_merge(conn, payload)
        return
    if kind == "rephrase":
        apply_rephrase(conn, payload)
        return
    if kind == "connect":
        apply_connect(conn, payload)
        return
    if kind == "prune":
        apply_prune(conn, payload)
        return
    raise ValueError(f"Unsupported proposal kind: {kind}")


def apply_merge(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    keep_id = str(payload.get("node_a_id") or payload.get("keep_node_id") or "")
    drop_id = str(payload.get("node_b_id") or payload.get("drop_node_id") or "")
    if not keep_id or not drop_id:
        raise ValueError("merge proposal requires node_a_id and node_b_id")
    keep = get_node(conn, keep_id)
    get_node(conn, drop_id)

    update_fields: dict[str, Any] = {}
    if payload.get("merged_name"):
        update_fields["name"] = str(payload["merged_name"])
    if payload.get("merged_text"):
        update_fields["text_representation"] = str(payload["merged_text"])
    if update_fields:
        update_node(conn, keep_id, **update_fields)

    for edge in get_edges_from(conn, drop_id):
        target_id = edge["target_id"]
        if target_id != keep_id and not _edge_exists(conn, keep_id, target_id, edge["relation"]):
            add_edge(conn, keep_id, target_id, edge["relation"], edge.get("properties") or {})
    for edge in get_edges_to(conn, drop_id):
        source_id = edge["source_id"]
        if source_id != keep_id and not _edge_exists(conn, source_id, keep_id, edge["relation"]):
            add_edge(conn, source_id, keep_id, edge["relation"], edge.get("properties") or {})

    conn.execute("UPDATE node_sources SET node_id = ? WHERE node_id = ?", (keep_id, drop_id))
    delete_node(conn, drop_id)
    update_node(conn, keep_id, type=keep["type"])


def apply_rephrase(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    node_id = str(payload.get("node_id") or "")
    proposed = payload.get("proposed_text")
    if not node_id or not proposed:
        raise ValueError("rephrase proposal requires node_id and proposed_text")
    update_node(conn, node_id, text_representation=str(proposed))


def apply_connect(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    source_id = str(payload.get("source_id") or "")
    target_id = str(payload.get("target_id") or "")
    relation = str(payload.get("relation") or "related_to")
    if not source_id or not target_id:
        raise ValueError("connect proposal requires source_id and target_id")
    get_node(conn, source_id)
    get_node(conn, target_id)
    if not _edge_exists(conn, source_id, target_id, relation):
        add_edge(conn, source_id, target_id, relation, {})


def apply_prune(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    node_id = str(payload.get("node_id") or "")
    if not node_id:
        raise ValueError("prune proposal requires node_id")
    delete_node(conn, node_id)


def _edge_exists(conn: sqlite3.Connection, source_id: str, target_id: str, relation: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM edges
        WHERE source_id = ? AND target_id = ? AND relation = ?
        LIMIT 1
        """,
        (source_id, target_id, relation),
    ).fetchone()
    return row is not None


__all__ = [
    "apply_connect",
    "apply_merge",
    "apply_proposal",
    "apply_prune",
    "apply_rephrase",
]

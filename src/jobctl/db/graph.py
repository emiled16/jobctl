"""Knowledge graph CRUD operations."""

import json
import sqlite3
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any


Node = dict[str, Any]
Edge = dict[str, Any]


def add_node(
    conn: sqlite3.Connection,
    type: str,
    name: str,
    properties: dict[str, Any] | None,
    text_representation: str,
) -> str:
    node_id = str(uuid.uuid4())
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO nodes (
            id, type, name, properties, text_representation, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, type, name, _to_json(properties), text_representation, now, now),
    )
    conn.commit()
    return node_id


def add_edge(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    relation: str,
    properties: dict[str, Any] | None,
) -> str:
    edge_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO edges (id, source_id, target_id, relation, properties, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (edge_id, source_id, target_id, relation, _to_json(properties), _utc_now()),
    )
    conn.commit()
    return edge_id


def edge_exists(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    relation: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM edges
        WHERE source_id = ? AND target_id = ? AND relation = ?
        LIMIT 1
        """,
        (source_id, target_id, relation),
    ).fetchone()
    return row is not None


def add_edge_if_missing(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    relation: str,
    properties: dict[str, Any] | None = None,
) -> str | None:
    if edge_exists(conn, source_id, target_id, relation):
        return None
    return add_edge(conn, source_id, target_id, relation, properties or {})


def add_node_source(
    conn: sqlite3.Connection,
    node_id: str,
    source_type: str,
    source_ref: str | None,
    confidence: float | None,
    source_quote: str | None,
) -> str:
    source_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO node_sources (
            id, node_id, source_type, source_ref, confidence, source_quote, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, node_id, source_type, source_ref, confidence, source_quote, _utc_now()),
    )
    conn.commit()
    return source_id


def merge_node_properties(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, incoming_value in (incoming or {}).items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = incoming_value
            continue
        if replace:
            merged[key] = incoming_value
            continue
        existing_value = merged[key]
        if isinstance(existing_value, list):
            additions = incoming_value if isinstance(incoming_value, list) else [incoming_value]
            merged[key] = existing_value + [
                item for item in additions if item not in existing_value
            ]
        elif isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged[key] = merge_node_properties(existing_value, incoming_value, replace=replace)
    return merged


def get_node(conn: sqlite3.Connection, node_id: str) -> Node:
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        raise KeyError(f"Node not found: {node_id}")
    return _node_from_row(row)


def get_nodes_by_type(conn: sqlite3.Connection, type: str) -> list[Node]:
    rows = conn.execute("SELECT * FROM nodes WHERE type = ? ORDER BY name", (type,)).fetchall()
    return [_node_from_row(row) for row in rows]


def get_edges_from(conn: sqlite3.Connection, node_id: str) -> list[Edge]:
    rows = conn.execute(
        """
        SELECT edges.*, nodes.id AS target_node_id, nodes.type AS target_type,
               nodes.name AS target_name, nodes.properties AS target_properties,
               nodes.text_representation AS target_text_representation,
               nodes.created_at AS target_created_at, nodes.updated_at AS target_updated_at
        FROM edges
        JOIN nodes ON nodes.id = edges.target_id
        WHERE edges.source_id = ?
        ORDER BY edges.created_at, edges.id
        """,
        (node_id,),
    ).fetchall()
    return [_edge_with_node_from_row(row, "target") for row in rows]


def get_edges_to(conn: sqlite3.Connection, node_id: str) -> list[Edge]:
    rows = conn.execute(
        """
        SELECT edges.*, nodes.id AS source_node_id, nodes.type AS source_type,
               nodes.name AS source_name, nodes.properties AS source_properties,
               nodes.text_representation AS source_text_representation,
               nodes.created_at AS source_created_at, nodes.updated_at AS source_updated_at
        FROM edges
        JOIN nodes ON nodes.id = edges.source_id
        WHERE edges.target_id = ?
        ORDER BY edges.created_at, edges.id
        """,
        (node_id,),
    ).fetchall()
    return [_edge_with_node_from_row(row, "source") for row in rows]


def get_subgraph(
    conn: sqlite3.Connection, node_id: str, depth: int = 2
) -> dict[str, list[Node] | list[Edge]]:
    if depth < 0:
        raise ValueError("depth must be greater than or equal to 0")

    nodes: dict[str, Node] = {node_id: get_node(conn, node_id)}
    edges: dict[str, Edge] = {}
    queue: deque[tuple[str, int]] = deque([(node_id, 0)])
    visited_at_depth: dict[str, int] = {node_id: 0}

    while queue:
        current_node_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        for edge in _plain_edges_from(conn, current_node_id):
            edges[edge["id"]] = edge
            target_id = edge["target_id"]
            if target_id not in nodes:
                nodes[target_id] = get_node(conn, target_id)
            next_depth = current_depth + 1
            if visited_at_depth.get(target_id, depth + 1) > next_depth:
                visited_at_depth[target_id] = next_depth
                queue.append((target_id, next_depth))

    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def update_node(conn: sqlite3.Connection, node_id: str, **kwargs: Any) -> None:
    allowed_fields = {"type", "name", "properties", "text_representation"}
    unknown_fields = set(kwargs) - allowed_fields
    if unknown_fields:
        joined_fields = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unknown node field(s): {joined_fields}")
    if not kwargs:
        return

    updates = []
    values: list[Any] = []
    for field, value in kwargs.items():
        updates.append(f"{field} = ?")
        values.append(_to_json(value) if field == "properties" else value)
    updates.append("updated_at = ?")
    values.append(_utc_now())
    values.append(node_id)

    cursor = conn.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", values)
    if cursor.rowcount == 0:
        raise KeyError(f"Node not found: {node_id}")
    conn.commit()


def delete_node(conn: sqlite3.Connection, node_id: str) -> None:
    cursor = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    if cursor.rowcount == 0:
        raise KeyError(f"Node not found: {node_id}")
    conn.commit()


def search_nodes(
    conn: sqlite3.Connection,
    type: str | None = None,
    name_contains: str | None = None,
) -> list[Node]:
    clauses = []
    values: list[Any] = []
    if type is not None:
        clauses.append("type = ?")
        values.append(type)
    if name_contains is not None:
        clauses.append("name LIKE ?")
        values.append(f"%{name_contains}%")

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM nodes {where_clause} ORDER BY name", values).fetchall()
    return [_node_from_row(row) for row in rows]


def _plain_edges_from(conn: sqlite3.Connection, node_id: str) -> list[Edge]:
    rows = conn.execute(
        "SELECT * FROM edges WHERE source_id = ? ORDER BY created_at, id",
        (node_id,),
    ).fetchall()
    return [_edge_from_row(row) for row in rows]


def _node_from_row(row: sqlite3.Row) -> Node:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "properties": _from_json(row["properties"]),
        "text_representation": row["text_representation"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _edge_from_row(row: sqlite3.Row) -> Edge:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "relation": row["relation"],
        "properties": _from_json(row["properties"]),
        "created_at": row["created_at"],
    }


def _edge_with_node_from_row(row: sqlite3.Row, node_key: str) -> Edge:
    edge = _edge_from_row(row)
    edge[node_key] = {
        "id": row[f"{node_key}_node_id"],
        "type": row[f"{node_key}_type"],
        "name": row[f"{node_key}_name"],
        "properties": _from_json(row[f"{node_key}_properties"]),
        "text_representation": row[f"{node_key}_text_representation"],
        "created_at": row[f"{node_key}_created_at"],
        "updated_at": row[f"{node_key}_updated_at"],
    }
    return edge


def _to_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _from_json(value: str | None) -> dict[str, Any]:
    if value is None:
        return {}
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        return {}
    return decoded


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

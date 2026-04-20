"""Knowledge-graph coverage analysis used by ChatView reports."""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["analyze_coverage"]


def analyze_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    roles = _nodes_by_type(conn, "role")
    roles_without_achievements = _roles_missing_relation(conn, "achieved")
    roles_without_skills = _roles_missing_relation(conn, "used_skill")

    coverage = {
        "roles_count": len(roles),
        "has_education": _node_count(conn, "education") > 0,
        "skills_count": _node_count(conn, "skill"),
        "achievements_count": _node_count(conn, "achievement"),
        "roles_without_achievements": roles_without_achievements,
        "roles_without_skills": roles_without_skills,
        "has_stories": _node_count(conn, "story") > 0,
        "missing_sections": [],
    }
    coverage["missing_sections"] = _missing_sections(coverage)
    return coverage


def _node_count(conn: sqlite3.Connection, node_type: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM nodes WHERE type = ?", (node_type,)
    ).fetchone()
    return int(row["count"])


def _nodes_by_type(conn: sqlite3.Connection, node_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM nodes WHERE type = ? ORDER BY name",
        (node_type,),
    ).fetchall()
    return [dict(row) for row in rows]


def _roles_missing_relation(conn: sqlite3.Connection, relation: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT nodes.*
        FROM nodes
        WHERE nodes.type = 'role'
          AND NOT EXISTS (
              SELECT 1
              FROM edges
              WHERE edges.source_id = nodes.id
                AND edges.relation = ?
          )
        ORDER BY nodes.name
        """,
        (relation,),
    ).fetchall()
    return [dict(row) for row in rows]


def _missing_sections(coverage: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if coverage["roles_count"] == 0:
        missing.append("roles")
    if not coverage["has_education"]:
        missing.append("education")
    if coverage["skills_count"] == 0:
        missing.append("skills")
    if coverage["achievements_count"] == 0:
        missing.append("achievements")
    if not coverage["has_stories"]:
        missing.append("stories")
    return missing

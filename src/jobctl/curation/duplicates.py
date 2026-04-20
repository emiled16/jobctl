"""Find likely duplicate pairs of graph nodes.

Uses a combination of cosine similarity over stored embeddings and fuzzy
name matching (``difflib``) to propose merge candidates.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Sequence

__all__ = ["DuplicateCandidate", "find_duplicate_candidates"]


@dataclass
class DuplicateCandidate:
    node_a: dict[str, Any]
    node_b: dict[str, Any]
    cosine_similarity: float
    name_similarity: float
    reason: str


def _load_embeddings(conn: sqlite3.Connection) -> list[tuple[str, list[float]]]:
    """Load ``(node_id, vector)`` pairs regardless of the storage backend."""
    row = conn.execute(
        """
        SELECT sql FROM sqlite_schema WHERE name = 'node_embeddings'
        """
    ).fetchone()
    using_vec = bool(row and row[0] and "USING VEC0" in row[0].upper())

    if using_vec:
        try:
            import sqlite_vec  # lazy

            rows = conn.execute("SELECT node_id, embedding FROM node_embeddings").fetchall()
            pairs: list[tuple[str, list[float]]] = []
            for r in rows:
                node_id, raw = r[0], r[1]
                try:
                    vector = list(sqlite_vec.deserialize_float32(raw))
                except Exception:
                    # Newer sqlite-vec stores in binary; fall back to json if present.
                    try:
                        vector = list(json.loads(raw))
                    except Exception:
                        continue
                pairs.append((node_id, vector))
            return pairs
        except Exception:
            pass

    rows = conn.execute("SELECT node_id, embedding FROM node_embeddings").fetchall()
    pairs = []
    for r in rows:
        node_id, raw = r[0], r[1]
        try:
            vector = list(json.loads(raw))
        except Exception:
            continue
        pairs.append((node_id, vector))
    return pairs


def _load_nodes_by_id(
    conn: sqlite3.Connection, node_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    if not node_ids:
        return {}
    placeholders = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"""
        SELECT id, type, name, text_representation
        FROM nodes
        WHERE id IN ({placeholders})
        """,
        list(node_ids),
    ).fetchall()
    return {
        r[0]: {
            "id": r[0],
            "type": r[1],
            "name": r[2],
            "text_representation": r[3],
        }
        for r in rows
    }


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def find_duplicate_candidates(
    conn: sqlite3.Connection,
    *,
    cosine_threshold: float = 0.92,
    fuzzy_threshold: float = 0.85,
    max_candidates: int = 200,
) -> list[DuplicateCandidate]:
    """Return likely duplicate node pairs ordered by descending cosine.

    Pairs that cross node types are skipped. Pairs above either threshold
    are returned (up to ``max_candidates``).
    """

    embeddings = _load_embeddings(conn)
    if not embeddings:
        return []

    node_ids = [node_id for node_id, _ in embeddings]
    node_lookup = _load_nodes_by_id(conn, node_ids)

    candidates: list[DuplicateCandidate] = []
    count = len(embeddings)
    for i in range(count):
        id_a, vec_a = embeddings[i]
        node_a = node_lookup.get(id_a)
        if node_a is None:
            continue
        for j in range(i + 1, count):
            id_b, vec_b = embeddings[j]
            node_b = node_lookup.get(id_b)
            if node_b is None:
                continue
            if node_a["type"] != node_b["type"]:
                continue
            cos = _cosine(vec_a, vec_b)
            name = _name_similarity(node_a["name"] or "", node_b["name"] or "")
            if cos < cosine_threshold and name < fuzzy_threshold:
                continue
            reason_parts = []
            if cos >= cosine_threshold:
                reason_parts.append(f"cosine={cos:.2f}")
            if name >= fuzzy_threshold:
                reason_parts.append(f"name={name:.2f}")
            candidates.append(
                DuplicateCandidate(
                    node_a=node_a,
                    node_b=node_b,
                    cosine_similarity=cos,
                    name_similarity=name,
                    reason=", ".join(reason_parts),
                )
            )

    candidates.sort(key=lambda c: c.cosine_similarity, reverse=True)
    return candidates[:max_candidates]

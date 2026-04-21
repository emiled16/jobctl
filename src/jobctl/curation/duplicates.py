"""Find likely duplicate pairs of graph nodes.

Uses a combination of cosine similarity over stored embeddings and fuzzy
name matching (``difflib``) to propose merge candidates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Sequence

from jobctl.rag.store import VectorFilter, VectorStore

__all__ = ["DuplicateCandidate", "find_duplicate_candidates"]


@dataclass
class DuplicateCandidate:
    node_a: dict[str, Any]
    node_b: dict[str, Any]
    cosine_similarity: float
    name_similarity: float
    reason: str


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


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def find_duplicate_candidates(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    embedding_client: Any,
    *,
    cosine_threshold: float = 0.92,
    fuzzy_threshold: float = 0.85,
    max_candidates: int = 200,
) -> list[DuplicateCandidate]:
    """Return likely duplicate node pairs ordered by descending cosine.

    Pairs that cross node types are skipped. Pairs above either threshold
    are returned (up to ``max_candidates``).
    """

    rows = conn.execute(
        """
        SELECT id, type, name, text_representation
        FROM nodes
        WHERE text_representation IS NOT NULL
        ORDER BY updated_at DESC
        """
    ).fetchall()
    if not rows:
        return []

    node_ids = [row["id"] for row in rows]
    node_lookup = _load_nodes_by_id(conn, node_ids)

    candidates: list[DuplicateCandidate] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        id_a = row["id"]
        node_a = node_lookup.get(id_a)
        if node_a is None:
            continue
        try:
            embedding = embedding_client.get_embedding(row["text_representation"])
        except AttributeError:
            embedding = embedding_client.embed([row["text_representation"]])[0]
        except Exception:
            continue
        try:
            hits = vector_store.search(
                embedding,
                top_k=12,
                filters=VectorFilter(node_type=node_a["type"]),
            )
        except Exception:
            hits = []
        for hit in hits:
            id_b = hit.node_id
            if id_a == id_b:
                continue
            pair = tuple(sorted((id_a, id_b)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            node_b = node_lookup.get(id_b)
            if node_b is None:
                continue
            cos = float(hit.score)
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

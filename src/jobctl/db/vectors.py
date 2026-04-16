"""sqlite-vec embedding operations."""

import json
import math
import sqlite3
from typing import Protocol

import sqlite_vec


EMBEDDING_DIMENSIONS = 1536


class EmbeddingClient(Protocol):
    def get_embedding(self, text: str) -> list[float]: ...

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]: ...


def init_vec(conn: sqlite3.Connection) -> None:
    try:
        sqlite_vec.load(conn)
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS node_embeddings
            USING vec0(node_id TEXT PRIMARY KEY, embedding float[{EMBEDDING_DIMENSIONS}])
            """
        )
    except (sqlite3.Error, AttributeError):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS node_embeddings (
                node_id TEXT PRIMARY KEY,
                embedding TEXT NOT NULL
            )
            """
        )
    conn.commit()


def upsert_embedding(conn: sqlite3.Connection, node_id: str, embedding: list[float]) -> None:
    _validate_embedding(embedding)
    if _uses_sqlite_vec(conn):
        conn.execute(
            """
            INSERT OR REPLACE INTO node_embeddings (node_id, embedding)
            VALUES (?, ?)
            """,
            (node_id, sqlite_vec.serialize_float32(embedding)),
        )
    else:
        conn.execute(
            """
            INSERT OR REPLACE INTO node_embeddings (node_id, embedding)
            VALUES (?, ?)
            """,
            (node_id, json.dumps(embedding)),
        )
    conn.commit()


def search_similar(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int = 10,
    type_filter: str | None = None,
) -> list[tuple[str, float]]:
    _validate_embedding(query_embedding)
    if top_k < 1:
        raise ValueError("top_k must be greater than 0")

    if _uses_sqlite_vec(conn):
        return _search_similar_with_sqlite_vec(conn, query_embedding, top_k, type_filter)
    return _search_similar_with_python(conn, query_embedding, top_k, type_filter)


def delete_embedding(conn: sqlite3.Connection, node_id: str) -> None:
    conn.execute("DELETE FROM node_embeddings WHERE node_id = ?", (node_id,))
    conn.commit()


def embed_node(conn: sqlite3.Connection, node_id: str, llm_client: EmbeddingClient) -> None:
    row = conn.execute(
        "SELECT text_representation FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Node not found: {node_id}")

    upsert_embedding(conn, node_id, llm_client.get_embedding(row["text_representation"]))


def embed_all_nodes(conn: sqlite3.Connection, llm_client: EmbeddingClient) -> int:
    rows = conn.execute(
        """
        SELECT nodes.id, nodes.text_representation
        FROM nodes
        LEFT JOIN node_embeddings ON node_embeddings.node_id = nodes.id
        WHERE node_embeddings.node_id IS NULL
        ORDER BY nodes.created_at, nodes.id
        """
    ).fetchall()
    if not rows:
        return 0

    texts = [row["text_representation"] for row in rows]
    embeddings = llm_client.get_embeddings_batch(texts)
    if len(embeddings) != len(rows):
        raise ValueError("Embedding client returned a different number of embeddings")

    for row, embedding in zip(rows, embeddings, strict=True):
        upsert_embedding(conn, row["id"], embedding)
    return len(rows)


def _search_similar_with_sqlite_vec(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int,
    type_filter: str | None,
) -> list[tuple[str, float]]:
    query_vector = sqlite_vec.serialize_float32(query_embedding)
    if type_filter is None:
        rows = conn.execute(
            """
            SELECT node_id, distance
            FROM node_embeddings
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (query_vector, top_k),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT node_embeddings.node_id, node_embeddings.distance
            FROM node_embeddings
            JOIN nodes ON nodes.id = node_embeddings.node_id
            WHERE node_embeddings.embedding MATCH ? AND k = ? AND nodes.type = ?
            ORDER BY node_embeddings.distance
            """,
            (query_vector, top_k, type_filter),
        ).fetchall()
    return [(row["node_id"], float(row["distance"])) for row in rows]


def _search_similar_with_python(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    top_k: int,
    type_filter: str | None,
) -> list[tuple[str, float]]:
    if type_filter is None:
        rows = conn.execute("SELECT node_id, embedding FROM node_embeddings").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT node_embeddings.node_id, node_embeddings.embedding
            FROM node_embeddings
            JOIN nodes ON nodes.id = node_embeddings.node_id
            WHERE nodes.type = ?
            """,
            (type_filter,),
        ).fetchall()

    distances = [
        (row["node_id"], _l2_distance(query_embedding, json.loads(row["embedding"])))
        for row in rows
    ]
    return sorted(distances, key=lambda item: item[1])[:top_k]


def _uses_sqlite_vec(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT sql
        FROM sqlite_schema
        WHERE name = 'node_embeddings'
        """
    ).fetchone()
    return bool(row and row["sql"] and "USING VEC0" in row["sql"].upper())


def _validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions")


def _l2_distance(left: list[float], right: list[float]) -> float:
    squared_deltas = (
        (left_value - right_value) ** 2 for left_value, right_value in zip(left, right, strict=True)
    )
    return math.sqrt(sum(squared_deltas))

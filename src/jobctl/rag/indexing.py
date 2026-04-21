"""Graph node indexing services for Qdrant-backed RAG."""

from __future__ import annotations

import sqlite3
from typing import Protocol

from jobctl.config import JobctlConfig
from jobctl.rag.store import EMBEDDING_DIMENSIONS, RagDocument, VectorFilter, VectorStore


class EmbeddingClient(Protocol):
    def get_embedding(self, text: str) -> list[float]: ...

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]: ...


def document_id_for_node(node_id: str) -> str:
    return f"node:{node_id}"


def document_id_to_node_id(document_id: str) -> str:
    return document_id.removeprefix("node:")


def index_node(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    node_id: str,
    embedding_client: EmbeddingClient,
    *,
    config: JobctlConfig | None = None,
) -> None:
    row = conn.execute(
        """
        SELECT id, type, name, text_representation, created_at, updated_at
        FROM nodes
        WHERE id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Node not found: {node_id}")
    embedding = embedding_client.get_embedding(row["text_representation"])
    vector_store.upsert_documents([_document_from_row(row, embedding, config=config)])


def index_nodes(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    node_ids: list[str],
    embedding_client: EmbeddingClient,
    *,
    config: JobctlConfig | None = None,
) -> int:
    if not node_ids:
        return 0
    placeholders = ",".join("?" * len(node_ids))
    rows = conn.execute(
        f"""
        SELECT id, type, name, text_representation, created_at, updated_at
        FROM nodes
        WHERE id IN ({placeholders})
        ORDER BY created_at, id
        """,
        node_ids,
    ).fetchall()
    return _index_rows(vector_store, rows, embedding_client, config=config)


def index_all_nodes(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    embedding_client: EmbeddingClient,
    *,
    config: JobctlConfig | None = None,
    force: bool = False,
) -> int:
    if force:
        rows = conn.execute(
            """
            SELECT id, type, name, text_representation, created_at, updated_at
            FROM nodes
            ORDER BY created_at, id
            """
        ).fetchall()
    else:
        existing = {document_id_to_node_id(doc_id) for doc_id in vector_store.list_document_ids()}
        rows = conn.execute(
            """
            SELECT id, type, name, text_representation, created_at, updated_at
            FROM nodes
            ORDER BY created_at, id
            """
        ).fetchall()
        rows = [row for row in rows if row["id"] not in existing]
    return _index_rows(vector_store, rows, embedding_client, config=config)


def delete_node_document(vector_store: VectorStore, node_id: str) -> None:
    vector_store.delete_documents([document_id_for_node(node_id)])


def _index_rows(
    vector_store: VectorStore,
    rows: list[sqlite3.Row],
    embedding_client: EmbeddingClient,
    *,
    config: JobctlConfig | None,
) -> int:
    if not rows:
        return 0
    texts = [row["text_representation"] for row in rows]
    if hasattr(embedding_client, "get_embeddings_batch"):
        embeddings = embedding_client.get_embeddings_batch(texts)
    else:
        embeddings = [embedding_client.get_embedding(text) for text in texts]
    if len(embeddings) != len(rows):
        raise ValueError("Embedding client returned a different number of embeddings")
    documents = [
        _document_from_row(row, embedding, config=config)
        for row, embedding in zip(rows, embeddings, strict=True)
    ]
    vector_store.upsert_documents(documents)
    return len(documents)


def _document_from_row(
    row: sqlite3.Row,
    embedding: list[float],
    *,
    config: JobctlConfig | None,
) -> RagDocument:
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions")
    return RagDocument(
        id=document_id_for_node(row["id"]),
        text=row["text_representation"],
        embedding=embedding,
        node_id=row["id"],
        node_type=row["type"],
        name=row["name"],
        embedding_model=config.llm.embedding_model if config is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def node_type_filter(node_type: str | None) -> VectorFilter | None:
    return VectorFilter(node_type=node_type) if node_type else None

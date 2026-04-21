"""Apply accepted curation proposal payloads to the graph."""

from __future__ import annotations

import sqlite3
from typing import Any

from jobctl.db.graph import (
    add_edge,
    add_edge_if_missing,
    add_node,
    add_node_source,
    delete_node,
    edge_exists,
    get_edges_from,
    get_edges_to,
    get_node,
    merge_node_properties,
    search_nodes,
    update_node,
)
from jobctl.config import JobctlConfig
from jobctl.llm.schemas import ExtractedFact
from jobctl.rag.indexing import delete_node_document, index_node
from jobctl.rag.store import VectorStore


def apply_proposal(
    conn: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    config: JobctlConfig | None = None,
) -> None:
    if kind == "merge":
        apply_merge(conn, payload, vector_store, llm_client, config=config)
        return
    if kind == "rephrase":
        apply_rephrase(conn, payload, vector_store, llm_client, config=config)
        return
    if kind == "connect":
        apply_connect(conn, payload)
        return
    if kind == "prune":
        apply_prune(conn, payload, vector_store)
        return
    if kind == "add_fact":
        apply_add_fact(conn, payload, vector_store, llm_client, config=config)
        return
    if kind == "update_fact":
        apply_update_fact(conn, payload, vector_store, llm_client, config=config)
        return
    if kind == "refine_experience":
        apply_refine_experience(conn, payload, vector_store, llm_client, config=config)
        return
    raise ValueError(f"Unsupported proposal kind: {kind}")


def apply_merge(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    *,
    config: JobctlConfig | None = None,
) -> None:
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
        if target_id != keep_id and not edge_exists(conn, keep_id, target_id, edge["relation"]):
            add_edge(conn, keep_id, target_id, edge["relation"], edge.get("properties") or {})
    for edge in get_edges_to(conn, drop_id):
        source_id = edge["source_id"]
        if source_id != keep_id and not edge_exists(conn, source_id, keep_id, edge["relation"]):
            add_edge(conn, source_id, keep_id, edge["relation"], edge.get("properties") or {})

    conn.execute("UPDATE node_sources SET node_id = ? WHERE node_id = ?", (keep_id, drop_id))
    delete_node(conn, drop_id)
    update_node(conn, keep_id, type=keep["type"])
    delete_node_document(vector_store, drop_id)
    _index_node_if_possible(conn, vector_store, keep_id, llm_client, config=config)


def apply_rephrase(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    *,
    config: JobctlConfig | None = None,
) -> None:
    node_id = str(payload.get("node_id") or "")
    proposed = payload.get("proposed_text")
    if not node_id or not proposed:
        raise ValueError("rephrase proposal requires node_id and proposed_text")
    update_node(conn, node_id, text_representation=str(proposed))
    _index_node_if_possible(conn, vector_store, node_id, llm_client, config=config)


def apply_connect(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    source_id = str(payload.get("source_id") or "")
    target_id = str(payload.get("target_id") or "")
    relation = str(payload.get("relation") or "related_to")
    if not source_id or not target_id:
        raise ValueError("connect proposal requires source_id and target_id")
    get_node(conn, source_id)
    get_node(conn, target_id)
    if not edge_exists(conn, source_id, target_id, relation):
        add_edge(conn, source_id, target_id, relation, {})


def apply_prune(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
) -> None:
    node_id = str(payload.get("node_id") or "")
    if not node_id:
        raise ValueError("prune proposal requires node_id")
    delete_node(conn, node_id)
    delete_node_document(vector_store, node_id)


def apply_add_fact(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    *,
    config: JobctlConfig | None = None,
) -> None:
    fact = ExtractedFact.model_validate(payload.get("fact") or payload)
    source_ref = str(payload.get("source_ref") or "")
    node_id = add_node(
        conn,
        fact.entity_type.lower(),
        fact.entity_name,
        fact.properties,
        fact.text_representation,
    )
    _index_node_if_possible(conn, vector_store, node_id, llm_client, config=config)
    add_node_source(
        conn,
        node_id,
        str(payload.get("source_type") or "resume"),
        source_ref,
        float(payload.get("confidence") or 1.0),
        fact.text_representation,
    )
    related_id = _resolve_related_node(conn, fact, vector_store, llm_client, config=config)
    if related_id is not None and fact.relation:
        add_edge_if_missing(conn, node_id, related_id, fact.relation, {})


def apply_update_fact(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    *,
    config: JobctlConfig | None = None,
) -> None:
    node_id = str(payload.get("node_id") or "")
    if not node_id:
        raise ValueError("update_fact proposal requires node_id")
    node = get_node(conn, node_id)
    proposed_properties = payload.get("proposed_properties")
    if proposed_properties is not None and not isinstance(proposed_properties, dict):
        raise ValueError("update_fact proposed_properties must be an object")
    update_fields: dict[str, Any] = {}
    if proposed_properties:
        update_fields["properties"] = merge_node_properties(
            node.get("properties"), proposed_properties
        )
    proposed_text = payload.get("proposed_text")
    if proposed_text:
        update_fields["text_representation"] = _append_once(
            node["text_representation"], str(proposed_text)
        )
    if update_fields:
        update_node(conn, node_id, **update_fields)
    add_node_source(
        conn,
        node_id,
        str(payload.get("source_type") or "resume"),
        str(payload.get("source_ref") or ""),
        float(payload.get("confidence") or 1.0),
        str(proposed_text or ""),
    )
    _index_node_if_possible(conn, vector_store, node_id, llm_client, config=config)


def apply_refine_experience(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    vector_store: VectorStore,
    llm_client: Any | None = None,
    *,
    config: JobctlConfig | None = None,
) -> None:
    target_node_id = payload.get("target_node_id")
    node_updates = payload.get("node_updates") or {}
    if target_node_id and isinstance(node_updates, dict):
        apply_update_fact(
            conn,
            {
                "node_id": target_node_id,
                "proposed_properties": node_updates,
                "proposed_text": payload.get("resume_ready_phrasing"),
                "source_type": "resume_refinement",
                "source_ref": payload.get("source_ref"),
                "confidence": 1.0,
            },
            vector_store,
            llm_client,
            config=config,
        )


def _resolve_related_node(
    conn: sqlite3.Connection,
    fact: ExtractedFact,
    vector_store: VectorStore,
    llm_client: Any | None,
    *,
    config: JobctlConfig | None = None,
) -> str | None:
    if not fact.related_to:
        return None
    matches = search_nodes(conn, name_contains=fact.related_to)
    exact = [node for node in matches if node["name"].lower() == fact.related_to.lower()]
    if exact:
        return exact[0]["id"]
    node_id = add_node(conn, "unknown", fact.related_to, {}, fact.related_to)
    _index_node_if_possible(conn, vector_store, node_id, llm_client, config=config)
    return node_id


def _index_node_if_possible(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    node_id: str,
    llm_client: Any | None,
    *,
    config: JobctlConfig | None = None,
) -> None:
    if llm_client is None or not hasattr(llm_client, "get_embedding"):
        return
    index_node(conn, vector_store, node_id, llm_client, config=config)


def _append_once(existing: str, addition: str) -> str:
    if not addition or addition in existing:
        return existing
    return f"{existing}\n{addition}"


__all__ = [
    "apply_connect",
    "apply_merge",
    "apply_proposal",
    "apply_prune",
    "apply_add_fact",
    "apply_update_fact",
    "apply_rephrase",
]

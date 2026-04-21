"""Tests for applying curation proposal payloads."""

from __future__ import annotations

import sqlite3

import pytest

from jobctl.curation.apply import apply_connect, apply_merge, apply_prune, apply_rephrase
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_edge, add_node, get_edges_from, get_node


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    connection = get_connection(tmp_path / "jobctl.db")
    try:
        yield connection
    finally:
        connection.close()


def test_rephrase_updates_node_text(conn: sqlite3.Connection, fake_vector_store) -> None:
    node_id = add_node(conn, "skill", "Python", {}, "Old text")

    apply_rephrase(conn, {"node_id": node_id, "proposed_text": "New text"}, fake_vector_store)

    assert get_node(conn, node_id)["text_representation"] == "New text"


def test_connect_creates_edge_once(conn: sqlite3.Connection) -> None:
    source = add_node(conn, "role", "Engineer", {}, "Role")
    target = add_node(conn, "skill", "Python", {}, "Skill")

    apply_connect(conn, {"source_id": source, "target_id": target, "relation": "used"})
    apply_connect(conn, {"source_id": source, "target_id": target, "relation": "used"})

    assert len(get_edges_from(conn, source)) == 1


def test_prune_deletes_node(conn: sqlite3.Connection, fake_vector_store) -> None:
    node_id = add_node(conn, "skill", "Unused", {}, "Unused")

    apply_prune(conn, {"node_id": node_id}, fake_vector_store)

    with pytest.raises(KeyError):
        get_node(conn, node_id)


def test_merge_preserves_relationships_and_sources(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    keep = add_node(conn, "skill", "Python", {}, "Python")
    drop = add_node(conn, "skill", "Py", {}, "Py")
    neighbor = add_node(conn, "role", "Engineer", {}, "Engineer")
    add_edge(conn, drop, neighbor, "used_by", {})
    conn.execute(
        """
        INSERT INTO node_sources
            (id, node_id, source_type, source_ref, confidence, source_quote, created_at)
        VALUES ('source-1', ?, 'resume', 'resume.md', 0.9, 'quote', 'now')
        """,
        (drop,),
    )
    conn.commit()

    apply_merge(
        conn,
        {
            "node_a_id": keep,
            "node_b_id": drop,
            "merged_name": "Python",
            "merged_text": "Python programming",
        },
        fake_vector_store,
    )

    assert get_node(conn, keep)["text_representation"] == "Python programming"
    with pytest.raises(KeyError):
        get_node(conn, drop)
    assert len(get_edges_from(conn, keep)) == 1
    row = conn.execute("SELECT node_id FROM node_sources WHERE id = 'source-1'").fetchone()
    assert row["node_id"] == keep

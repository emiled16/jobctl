import sqlite3
import time
from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import (
    add_edge,
    add_node,
    delete_node,
    get_edges_from,
    get_edges_to,
    get_node,
    get_nodes_by_type,
    get_subgraph,
    search_nodes,
    update_node,
)


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_insert_node_and_retrieve_by_id(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {"years": 8}, "Python programming")

    node = get_node(conn, node_id)

    assert node["id"] == node_id
    assert node["type"] == "skill"
    assert node["name"] == "Python"
    assert node["properties"] == {"years": 8}
    assert node["text_representation"] == "Python programming"


def test_insert_edge_and_verify_foreign_key(conn: sqlite3.Connection) -> None:
    source_id = add_node(conn, "role", "Engineer", {}, "Engineer role")
    target_id = add_node(conn, "company", "Acme", {}, "Acme company")

    edge_id = add_edge(conn, source_id, target_id, "worked_at", {"start_date": "2024-01"})

    outgoing_edges = get_edges_from(conn, source_id)
    incoming_edges = get_edges_to(conn, target_id)
    assert outgoing_edges[0]["id"] == edge_id
    assert outgoing_edges[0]["target"]["id"] == target_id
    assert incoming_edges[0]["source"]["id"] == source_id

    with pytest.raises(sqlite3.IntegrityError):
        add_edge(conn, source_id, "missing-node", "worked_at", {})


def test_get_subgraph_with_depth_1_and_depth_2(conn: sqlite3.Connection) -> None:
    root_id = add_node(conn, "person", "User", {}, "User")
    role_id = add_node(conn, "role", "Engineer", {}, "Engineer")
    company_id = add_node(conn, "company", "Acme", {}, "Acme")
    skill_id = add_node(conn, "skill", "Python", {}, "Python")
    add_edge(conn, root_id, role_id, "held_role", {})
    add_edge(conn, role_id, company_id, "worked_at", {})
    add_edge(conn, company_id, skill_id, "used_skill", {})

    depth_1 = get_subgraph(conn, root_id, depth=1)
    depth_2 = get_subgraph(conn, root_id, depth=2)

    assert {node["id"] for node in depth_1["nodes"]} == {root_id, role_id}
    assert len(depth_1["edges"]) == 1
    assert {node["id"] for node in depth_2["nodes"]} == {root_id, role_id, company_id}
    assert len(depth_2["edges"]) == 2


def test_search_nodes_with_type_filter(conn: sqlite3.Connection) -> None:
    add_node(conn, "skill", "Python", {}, "Python")
    add_node(conn, "skill", "SQL", {}, "SQL")
    add_node(conn, "company", "Pythonic Labs", {}, "Pythonic Labs")

    skill_results = search_nodes(conn, type="skill")
    named_results = search_nodes(conn, name_contains="Python")
    filtered_results = search_nodes(conn, type="skill", name_contains="Python")

    assert {node["name"] for node in skill_results} == {"Python", "SQL"}
    assert {node["name"] for node in named_results} == {"Python", "Pythonic Labs"}
    assert [node["name"] for node in filtered_results] == ["Python"]
    assert [node["name"] for node in get_nodes_by_type(conn, "company")] == ["Pythonic Labs"]


def test_delete_node_cascades_to_edges(conn: sqlite3.Connection) -> None:
    source_id = add_node(conn, "role", "Engineer", {}, "Engineer")
    target_id = add_node(conn, "company", "Acme", {}, "Acme")
    add_edge(conn, source_id, target_id, "worked_at", {})

    delete_node(conn, target_id)

    assert get_edges_from(conn, source_id) == []
    with pytest.raises(KeyError):
        get_node(conn, target_id)


def test_update_node_changes_fields_and_updated_at(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {"years": 8}, "Python")
    original_node = get_node(conn, node_id)
    time.sleep(0.001)

    update_node(
        conn,
        node_id,
        name="Python 3",
        properties={"years": 9},
        text_representation="Python 3 programming",
    )

    updated_node = get_node(conn, node_id)
    assert updated_node["name"] == "Python 3"
    assert updated_node["properties"] == {"years": 9}
    assert updated_node["text_representation"] == "Python 3 programming"
    assert updated_node["updated_at"] != original_node["updated_at"]


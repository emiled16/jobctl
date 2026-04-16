import sqlite3
from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import add_node
from jobctl.db.vectors import (
    EMBEDDING_DIMENSIONS,
    delete_embedding,
    embed_all_nodes,
    embed_node,
    search_similar,
    upsert_embedding,
)


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.single_texts: list[str] = []
        self.batch_texts: list[list[str]] = []

    def get_embedding(self, text: str) -> list[float]:
        self.single_texts.append(text)
        return make_embedding(0.25)

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_texts.append(texts)
        return [make_embedding(float(index)) for index, _ in enumerate(texts)]


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_upsert_embedding_inserts_and_replaces(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {}, "Python")

    upsert_embedding(conn, node_id, make_embedding(1.0))
    upsert_embedding(conn, node_id, make_embedding(2.0))

    assert search_similar(conn, make_embedding(2.0), top_k=1) == [(node_id, 0.0)]


def test_search_similar_returns_known_ordering(conn: sqlite3.Connection) -> None:
    near_id = add_node(conn, "skill", "Near", {}, "Near")
    middle_id = add_node(conn, "skill", "Middle", {}, "Middle")
    far_id = add_node(conn, "skill", "Far", {}, "Far")
    upsert_embedding(conn, near_id, make_embedding(0.0))
    upsert_embedding(conn, middle_id, make_embedding(1.0))
    upsert_embedding(conn, far_id, make_embedding(3.0))

    results = search_similar(conn, make_embedding(0.2), top_k=3)

    assert [node_id for node_id, _distance in results] == [near_id, middle_id, far_id]
    assert results[0][1] < results[1][1] < results[2][1]


def test_delete_embedding_removes_row(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {}, "Python")
    upsert_embedding(conn, node_id, make_embedding(1.0))

    delete_embedding(conn, node_id)

    assert search_similar(conn, make_embedding(1.0), top_k=1) == []


def test_search_similar_type_filter_only_returns_matching_nodes(conn: sqlite3.Connection) -> None:
    skill_id = add_node(conn, "skill", "Python", {}, "Python")
    company_id = add_node(conn, "company", "Pythonic Labs", {}, "Pythonic Labs")
    upsert_embedding(conn, skill_id, make_embedding(0.0))
    upsert_embedding(conn, company_id, make_embedding(0.1))

    results = search_similar(conn, make_embedding(0.1), top_k=10, type_filter="skill")

    assert results == [(skill_id, pytest.approx(0.1))]


def test_embed_node_uses_text_representation(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {}, "Python programming")
    client = FakeEmbeddingClient()

    embed_node(conn, node_id, client)

    assert client.single_texts == ["Python programming"]
    assert search_similar(conn, make_embedding(0.25), top_k=1)[0][0] == node_id


def test_embed_all_nodes_embeds_only_missing_nodes(conn: sqlite3.Connection) -> None:
    existing_id = add_node(conn, "skill", "Existing", {}, "Existing text")
    missing_id = add_node(conn, "skill", "Missing", {}, "Missing text")
    upsert_embedding(conn, existing_id, make_embedding(9.0))
    client = FakeEmbeddingClient()

    embedded_count = embed_all_nodes(conn, client)

    assert embedded_count == 1
    assert client.batch_texts == [["Missing text"]]
    assert search_similar(conn, make_embedding(0.0), top_k=1)[0][0] == missing_id


def test_embedding_dimension_is_validated(conn: sqlite3.Connection) -> None:
    node_id = add_node(conn, "skill", "Python", {}, "Python")

    with pytest.raises(ValueError, match=str(EMBEDDING_DIMENSIONS)):
        upsert_embedding(conn, node_id, [1.0, 2.0])


def make_embedding(first_value: float) -> list[float]:
    embedding = [0.0] * EMBEDDING_DIMENSIONS
    embedding[0] = first_value
    return embedding

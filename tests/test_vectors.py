from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import add_node
from jobctl.rag.indexing import document_id_for_node, index_all_nodes, index_node
from jobctl.rag.store import EMBEDDING_DIMENSIONS


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


def test_index_node_uses_text_representation(fake_vector_store) -> None:
    conn = get_connection(Path(":memory:"))
    try:
        node_id = add_node(conn, "skill", "Python", {}, "Python programming")
        client = FakeEmbeddingClient()

        index_node(conn, fake_vector_store, node_id, client)

        assert client.single_texts == ["Python programming"]
        document = fake_vector_store.documents[document_id_for_node(node_id)]
        assert document.node_id == node_id
        assert document.node_type == "skill"
        assert document.name == "Python"
    finally:
        conn.close()


def test_index_all_nodes_indexes_only_missing_documents(fake_vector_store) -> None:
    conn = get_connection(Path(":memory:"))
    try:
        existing_id = add_node(conn, "skill", "Existing", {}, "Existing text")
        missing_id = add_node(conn, "skill", "Missing", {}, "Missing text")
        fake_vector_store.documents[document_id_for_node(existing_id)] = object()
        client = FakeEmbeddingClient()

        indexed_count = index_all_nodes(conn, fake_vector_store, client)

        assert indexed_count == 1
        assert client.batch_texts == [["Missing text"]]
        assert document_id_for_node(missing_id) in fake_vector_store.documents
    finally:
        conn.close()


def test_index_node_validates_embedding_dimension(fake_vector_store) -> None:
    conn = get_connection(Path(":memory:"))
    try:
        node_id = add_node(conn, "skill", "Python", {}, "Python")

        class BadClient:
            def get_embedding(self, text: str) -> list[float]:
                return [1.0, 2.0]

        with pytest.raises(ValueError, match=str(EMBEDDING_DIMENSIONS)):
            index_node(conn, fake_vector_store, node_id, BadClient())
    finally:
        conn.close()


def make_embedding(first_value: float) -> list[float]:
    embedding = [0.0] * EMBEDDING_DIMENSIONS
    embedding[0] = first_value
    return embedding

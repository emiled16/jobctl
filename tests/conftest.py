"""Shared pytest fixtures for the jobctl test suite."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolSpec
from jobctl.rag.store import RagDocument, VectorFilter, VectorHit


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeLLMProvider:
    """In-memory LLMProvider used throughout the test suite."""

    def __init__(
        self,
        chat_reply: str = "ok",
        embedding_dimensions: int = 8,
    ) -> None:
        self.chat_reply = chat_reply
        self.embedding_dimensions = embedding_dimensions
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        self.calls.append({"kind": "chat", "messages": messages, "tools": tools})
        return {"content": self.chat_reply}

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        self.calls.append({"kind": "stream", "messages": messages, "tools": tools})
        for token in self.chat_reply.split():
            yield {"delta": f"{token} "}
        yield {"done": True}

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append({"kind": "embed", "texts": texts})
        return [
            [float((i + j) % 7) for j in range(self.embedding_dimensions)]
            for i, _ in enumerate(texts)
        ]


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()


class FakeVectorStore:
    def __init__(self, hits: list[VectorHit] | None = None) -> None:
        self.documents: dict[str, RagDocument] = {}
        self.hits = hits
        self.deleted: list[str] = []

    def ensure_ready(self) -> None:
        return None

    def upsert_documents(self, documents: list[RagDocument]) -> None:
        for document in documents:
            self.documents[document.id] = document

    def delete_documents(self, ids: list[str]) -> None:
        self.deleted.extend(ids)
        for document_id in ids:
            self.documents.pop(document_id, None)

    def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 10,
        filters: VectorFilter | None = None,
    ) -> list[VectorHit]:
        if self.hits is not None:
            return self.hits[:top_k]
        hits = [
            VectorHit(
                id=document.id,
                score=1.0,
                node_id=document.node_id,
                node_type=document.node_type,
                name=document.name,
                text=document.text,
                payload=document.payload(),
            )
            for document in self.documents.values()
            if filters is None
            or filters.node_type is None
            or document.node_type == filters.node_type
        ]
        return hits[:top_k]

    def list_document_ids(self, filters: VectorFilter | None = None) -> list[str]:
        return list(self.documents)

    def count_documents(self, filters: VectorFilter | None = None) -> int:
        return len(self.list_document_ids(filters))

    def close(self) -> None:
        return None


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    return FakeVectorStore()

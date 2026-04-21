"""Vector store contracts for RAG data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


EMBEDDING_DIMENSIONS = 1536


@dataclass(frozen=True)
class RagDocument:
    id: str
    text: str
    embedding: list[float]
    node_id: str
    node_type: str
    name: str
    source_type: str | None = None
    source_ref: str | None = None
    embedding_model: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        payload = {
            "document_id": self.id,
            "text": self.text,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "name": self.name,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "embedding_model": self.embedding_model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        payload.update(self.metadata)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class VectorHit:
    id: str
    score: float
    node_id: str
    node_type: str | None = None
    name: str | None = None
    text: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorFilter:
    node_ids: list[str] | None = None
    node_type: str | None = None
    source_type: str | None = None
    source_ref: str | None = None


class VectorStore(Protocol):
    def ensure_ready(self) -> None: ...

    def upsert_documents(self, documents: list[RagDocument]) -> None: ...

    def delete_documents(self, ids: list[str]) -> None: ...

    def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 10,
        filters: VectorFilter | None = None,
    ) -> list[VectorHit]: ...

    def list_document_ids(self, filters: VectorFilter | None = None) -> list[str]: ...

    def count_documents(self, filters: VectorFilter | None = None) -> int: ...

    def close(self) -> None: ...


class NoopVectorStore:
    """No-op vector store for tests and explicitly degraded contexts."""

    def ensure_ready(self) -> None:
        return None

    def upsert_documents(self, documents: list[RagDocument]) -> None:
        return None

    def delete_documents(self, ids: list[str]) -> None:
        return None

    def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 10,
        filters: VectorFilter | None = None,
    ) -> list[VectorHit]:
        return []

    def list_document_ids(self, filters: VectorFilter | None = None) -> list[str]:
        return []

    def count_documents(self, filters: VectorFilter | None = None) -> int:
        return 0

    def close(self) -> None:
        return None

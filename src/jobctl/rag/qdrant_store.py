"""Qdrant-backed vector storage."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from jobctl.config import VectorStoreConfig
from jobctl.rag.store import EMBEDDING_DIMENSIONS, RagDocument, VectorFilter, VectorHit


class QdrantVectorStore:
    def __init__(
        self,
        *,
        config: VectorStoreConfig,
        project_root: Path,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self.config = config
        self.project_root = project_root
        self.dimensions = dimensions
        self.collection = config.collection
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient

            if self.config.mode == "local":
                path = Path(self.config.path)
                if not path.is_absolute():
                    path = self.project_root / path
                path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(path))
            else:
                api_key = os.environ.get(self.config.api_key_env) or None
                self._client = QdrantClient(url=self.config.url, api_key=api_key)
        return self._client

    def ensure_ready(self) -> None:
        from qdrant_client import models

        distance = _distance(self.config.distance)
        vector_params = models.VectorParams(size=self.dimensions, distance=distance)
        try:
            collection = self.client.get_collection(self.collection)
        except Exception:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=vector_params,
            )
            return

        current_size = getattr(getattr(collection.config.params, "vectors", None), "size", None)
        if current_size is not None and int(current_size) != self.dimensions:
            raise ValueError(
                f"Qdrant collection {self.collection!r} has vector size {current_size}; "
                f"expected {self.dimensions}"
            )

    def upsert_documents(self, documents: list[RagDocument]) -> None:
        if not documents:
            return
        from qdrant_client import models

        points = []
        for document in documents:
            _validate_embedding(document.embedding, self.dimensions)
            points.append(
                models.PointStruct(
                    id=_point_id(document.id),
                    vector=document.embedding,
                    payload=document.payload(),
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)

    def delete_documents(self, ids: list[str]) -> None:
        if not ids:
            return
        from qdrant_client import models

        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=[_point_id(value) for value in ids]),
        )

    def search(
        self,
        embedding: list[float],
        *,
        top_k: int = 10,
        filters: VectorFilter | None = None,
    ) -> list[VectorHit]:
        _validate_embedding(embedding, self.dimensions)
        if top_k < 1:
            raise ValueError("top_k must be greater than 0")
        query_filter = _qdrant_filter(filters)
        if hasattr(self.client, "query_points"):
            result = self.client.query_points(
                collection_name=self.collection,
                query=embedding,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            points = getattr(result, "points", result)
        else:
            points = self.client.search(
                collection_name=self.collection,
                query_vector=embedding,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        return [_hit_from_point(point) for point in points]

    def list_document_ids(self, filters: VectorFilter | None = None) -> list[str]:
        ids: list[str] = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=_qdrant_filter(filters),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = getattr(point, "payload", None) or {}
                document_id = payload.get("document_id")
                if isinstance(document_id, str):
                    ids.append(document_id)
            if offset is None:
                return ids

    def count_documents(self, filters: VectorFilter | None = None) -> int:
        try:
            result = self.client.count(
                collection_name=self.collection,
                count_filter=_qdrant_filter(filters),
                exact=True,
            )
            return int(result.count)
        except Exception:
            return len(self.list_document_ids(filters))

    def close(self) -> None:
        if self._client is None:
            return
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
        self._client = None


def _validate_embedding(embedding: list[float], dimensions: int) -> None:
    if len(embedding) != dimensions:
        raise ValueError(f"Embedding must have {dimensions} dimensions")


def _point_id(document_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jobctl-rag:{document_id}"))


def _distance(distance: str) -> Any:
    from qdrant_client import models

    normalized = distance.lower()
    if normalized == "dot":
        return models.Distance.DOT
    if normalized == "euclid":
        return models.Distance.EUCLID
    return models.Distance.COSINE


def _qdrant_filter(filters: VectorFilter | None) -> Any | None:
    if filters is None:
        return None
    from qdrant_client import models

    must = []
    if filters.node_type:
        must.append(models.FieldCondition(key="node_type", match=models.MatchValue(value=filters.node_type)))
    if filters.source_type:
        must.append(
            models.FieldCondition(key="source_type", match=models.MatchValue(value=filters.source_type))
        )
    if filters.source_ref:
        must.append(models.FieldCondition(key="source_ref", match=models.MatchValue(value=filters.source_ref)))
    if filters.node_ids:
        must.append(models.FieldCondition(key="node_id", match=models.MatchAny(any=filters.node_ids)))
    return models.Filter(must=must) if must else None


def _hit_from_point(point: Any) -> VectorHit:
    payload = getattr(point, "payload", None) or {}
    score = getattr(point, "score", 0.0)
    document_id = payload.get("document_id") or str(getattr(point, "id", ""))
    node_id = str(payload.get("node_id") or document_id)
    return VectorHit(
        id=str(document_id),
        score=float(score),
        node_id=node_id,
        node_type=payload.get("node_type"),
        name=payload.get("name"),
        text=payload.get("text"),
        payload=dict(payload),
    )

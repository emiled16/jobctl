"""Vector store factory."""

from __future__ import annotations

from pathlib import Path

from jobctl.config import JobctlConfig
from jobctl.rag.qdrant_store import QdrantVectorStore
from jobctl.rag.store import VectorStore


def create_vector_store(config: JobctlConfig, project_root: Path) -> VectorStore:
    if config.vector_store.provider != "qdrant":
        raise ValueError(f"Unsupported vector store provider: {config.vector_store.provider}")
    store = QdrantVectorStore(config=config.vector_store, project_root=project_root)
    store.ensure_ready()
    return store

"""Adapters bridging LLMProvider to embedding-client interfaces."""

from __future__ import annotations

from jobctl.llm.base import LLMProvider


class EmbeddingAdapter:
    """Adapt an :class:`LLMProvider` to the RAG indexing embedding interface.

    RAG indexing expects ``get_embedding`` and ``get_embeddings_batch``
    methods. This adapter forwards both to ``LLMProvider.embed``.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def get_embedding(self, text: str) -> list[float]:
        embeddings = self._provider.embed([text])
        if not embeddings:
            raise RuntimeError("LLMProvider.embed returned no embeddings")
        return embeddings[0]

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        return self._provider.embed(texts)


def as_embedding_client(provider: LLMProvider) -> EmbeddingAdapter:
    return EmbeddingAdapter(provider)


__all__ = ["EmbeddingAdapter", "as_embedding_client"]

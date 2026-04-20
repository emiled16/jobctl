"""Codex CLI LLM provider.

Wraps the existing Codex subprocess + local HuggingFace transformer embedder
behind the LLMProvider protocol so the rest of the codebase can treat it the
same way as OpenAI or Ollama.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolSpec
from jobctl.llm.client import (  # noqa: F401 -- re-exported for backward compatibility
    DEFAULT_EMBEDDING_MODEL,
    CodexRunner,
    LLMClient,
    TransformerEmbedder,
    _messages_to_prompt,
    get_embeddings_batch,
)


class CodexCLIProvider:
    """LLMProvider that drives a local Codex CLI binary for chat.

    Embeddings are delegated to a local HuggingFace transformer model via the
    existing ``TransformerEmbedder``.
    """

    def __init__(
        self,
        chat_model: str,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        codex_binary: str = "codex",
        cwd: Path | None = None,
        runner: CodexRunner | None = None,
    ) -> None:
        self.chat_model = chat_model
        self.embedding_model = embedding_model
        self._client = LLMClient(
            api_key="",
            model=chat_model,
            codex_binary=codex_binary,
            cwd=cwd,
            runner=runner,
        )

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        content = self._client.chat(list(messages), temperature=temperature)
        return {"content": content}

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        content = self._client.chat(list(messages), temperature=temperature)
        if content:
            yield {"delta": content}
        yield {"done": True}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return get_embeddings_batch(texts, model=self.embedding_model)

    @property
    def underlying_client(self) -> LLMClient:
        return self._client


__all__ = ["CodexCLIProvider"]

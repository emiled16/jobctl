"""Shared pytest fixtures for the jobctl test suite."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolSpec


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
        return [[float((i + j) % 7) for j in range(self.embedding_dimensions)] for i, _ in enumerate(texts)]


@pytest.fixture
def fake_provider() -> FakeLLMProvider:
    return FakeLLMProvider()

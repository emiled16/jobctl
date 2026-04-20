"""LLM provider protocol and common message/response types."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, TypedDict, runtime_checkable


class ToolCall(TypedDict, total=False):
    """A tool call emitted by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


class Message(TypedDict, total=False):
    """A chat message exchanged with an LLM.

    ``role`` is one of ``"system"``, ``"user"``, ``"assistant"``, or ``"tool"``.
    """

    role: str
    content: str
    tool_calls: list[ToolCall]
    tool_call_id: str
    name: str


class ChatResponse(TypedDict, total=False):
    """Full, non-streaming response from an LLM chat call."""

    content: str
    tool_calls: list[ToolCall]


class ChatChunk(TypedDict, total=False):
    """A single streamed chunk from an LLM chat call."""

    delta: str
    tool_call_delta: ToolCall
    done: bool


class ToolSpec(TypedDict, total=False):
    """Declarative description of a callable tool.

    ``parameters`` is a JSON Schema object describing the argument shape.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@runtime_checkable
class LLMProvider(Protocol):
    """Common interface for swappable LLM backends."""

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse: ...

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


__all__ = [
    "ChatChunk",
    "ChatResponse",
    "LLMProvider",
    "Message",
    "ToolCall",
    "ToolSpec",
]

"""Unit tests for ``chat_node``."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

from jobctl.agent.nodes.chat_node import chat_node
from jobctl.agent.state import new_state
from jobctl.core.events import (
    AgentDoneEvent,
    AgentTokenEvent,
    AsyncEventBus,
)
from jobctl.llm.base import ChatChunk, ChatResponse, Message


class _FakeStreamingProvider:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks
        self.seen_messages: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:  # pragma: no cover - unused in streaming path
        raise NotImplementedError

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        self.seen_messages.append(list(messages))
        for token in self._chunks:
            yield ChatChunk(delta=token)
        yield ChatChunk(done=True)

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        return [[0.0] for _ in texts]


def _collect_events(bus: AsyncEventBus, count: int) -> list[Any]:
    async def drain() -> list[Any]:
        queue = bus.subscribe()
        events = []
        for _ in range(count):
            events.append(await asyncio.wait_for(queue.get(), timeout=1))
        return events

    return asyncio.run(drain())


def test_chat_node_streams_tokens_and_appends_assistant_message() -> None:
    provider = _FakeStreamingProvider(["Hello", ", ", "world"])
    bus = AsyncEventBus()

    async def run() -> None:
        bus.attach_loop(asyncio.get_running_loop())
        queue = bus.subscribe()
        state = new_state("session-1")
        state["messages"] = [Message(role="user", content="Hi")]

        result = chat_node(state, provider=provider, bus=bus)

        tokens: list[str] = []
        done: AgentDoneEvent | None = None
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=0.25)
                if isinstance(event, AgentTokenEvent):
                    tokens.append(event.token)
                elif isinstance(event, AgentDoneEvent):
                    done = event
                    break
        except TimeoutError:
            pass

        assert tokens == ["Hello", ", ", "world"]
        assert done is not None
        assert done.role == "assistant"
        assert done.content == "Hello, world"

        assert provider.seen_messages, "provider should have been called"
        sent = provider.seen_messages[0]
        assert sent[0]["role"] == "system"
        assert sent[-1] == {"role": "user", "content": "Hi"}

        assert result["messages"][-1] == {
            "role": "assistant",
            "content": "Hello, world",
        }

    asyncio.run(run())

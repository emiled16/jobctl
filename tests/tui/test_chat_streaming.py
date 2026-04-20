"""TUI tests for provider streaming rendered in ChatView."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from textual.css.query import NoMatches

from jobctl.config import JobctlConfig
from jobctl.db.connection import get_connection
from jobctl.llm.base import ChatChunk, ChatResponse, Message, ToolSpec
from jobctl.tui.app import JobctlApp
from jobctl.tui.views.chat import ChatView
from jobctl.tui.widgets.streaming_message import StreamingMessage


class DelayedStreamProvider:
    """Fake provider that spaces stream chunks far enough for UI assertions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chunks = ("alpha ", "beta ", "gamma")

    def chat(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        self.calls.append({"kind": "chat", "messages": messages, "tools": tools})
        return {"content": "alpha beta gamma"}

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.7,
    ) -> Iterator[ChatChunk]:
        self.calls.append({"kind": "stream", "messages": messages, "tools": tools})
        for chunk in self.chunks:
            yield {"delta": chunk}
            time.sleep(0.05)
        yield {"done": True}

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append({"kind": "embed", "texts": texts})
        return [[0.0] * 8 for _ in texts]


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            matched = predicate()
        except NoMatches:
            matched = False
        if matched:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def _make_app(tmp_path: Path, provider: DelayedStreamProvider) -> JobctlApp:
    conn = get_connection(tmp_path / ".jobctl.db")
    return JobctlApp(
        conn=conn,
        project_root=tmp_path,
        config=JobctlConfig(),
        provider=provider,
        start_screen="chat",
    )


@pytest.mark.anyio
async def test_chat_renders_partial_stream_before_final_message(tmp_path: Path) -> None:
    provider = DelayedStreamProvider()
    app = _make_app(tmp_path, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one(ChatView)

        lines_before = len(chat.query_one("#chat-log").lines)
        chat._handle_submission("stream a reply")

        await _wait_until(
            lambda: bool(chat.query_one("#streaming-assistant-message", StreamingMessage).content)
        )
        live = chat.query_one("#streaming-assistant-message", StreamingMessage)
        assert "alpha" in live.content
        assert live.content != "alpha beta gamma"

        await _wait_until(
            lambda: len([call for call in provider.calls if call["kind"] == "stream"]) == 1
            and chat._stream.widget is None,
            timeout=2.0,
        )
        with pytest.raises(NoMatches):
            chat.query_one("#streaming-assistant-message", StreamingMessage)

        log = chat.query_one("#chat-log")
        assert len(log.lines) == lines_before + 2
        assert chat._stream.buffer == ""

        await app.action_quit()

    if isinstance(app.conn, sqlite3.Connection):
        app.conn.close()

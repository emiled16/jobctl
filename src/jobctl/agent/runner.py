"""Bridge between the Textual TUI and the compiled LangGraph graph."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

from jobctl.agent.session import load_session, save_session
from jobctl.agent.state import AgentState, new_state
from jobctl.core.events import AgentDoneEvent, AsyncEventBus
from jobctl.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


class LangGraphRunner:
    """Coordinates LangGraph invocations with the event bus."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        conn: sqlite3.Connection,
        bus: AsyncEventBus,
        session_id: str,
        store: Any | None = None,
        runner: Any | None = None,
        config: Any | None = None,
    ) -> None:
        self.provider = provider
        self.conn = conn
        self.bus = bus
        self.session_id = session_id
        self.store = store
        self.runner = runner
        self.config = config
        self._compiled: Any | None = None

    def _ensure_graph(self) -> Any:
        if self._compiled is None:
            from jobctl.agent.graph import build_graph

            self._compiled = build_graph(
                provider=self.provider,
                conn=self.conn,
                bus=self.bus,
                store=self.store,
                runner=self.runner,
                config=self.config,
            )
        return self._compiled

    def _load_state(self) -> AgentState:
        try:
            loaded = load_session(self.conn, self.session_id)
        except Exception:
            loaded = None
        return loaded or new_state(self.session_id)

    async def submit(self, user_message: str) -> AgentState:
        """Append ``user_message`` to session state and run the graph."""
        state = self._load_state()
        messages = list(state.get("messages") or [])
        messages.append(Message(role="user", content=user_message))
        state["messages"] = messages

        self.bus.publish(AgentDoneEvent(role="user", content=user_message))

        graph = self._ensure_graph()
        try:
            result = await graph.ainvoke(state)
        except Exception:
            logger.exception("LangGraph invocation failed")
            raise

        if isinstance(result, dict):
            state = result  # type: ignore[assignment]

        try:
            save_session(self.conn, state)
        except Exception:
            logger.exception("failed to persist agent session")
        return state

    def submit_background(
        self,
        user_message: str,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> asyncio.Future[AgentState]:
        """Schedule :meth:`submit` on ``loop`` (default: running loop)."""
        target_loop = loop or asyncio.get_event_loop()
        return asyncio.run_coroutine_threadsafe(
            self.submit(user_message), target_loop
        )  # type: ignore[return-value]


__all__ = ["LangGraphRunner"]

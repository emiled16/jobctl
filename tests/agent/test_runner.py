"""Tests for LangGraphRunner workflow submission helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobctl.agent.runner import LangGraphRunner
from jobctl.agent.state import AgentState, make_workflow_request
from jobctl.core.events import AsyncEventBus
from jobctl.db.connection import get_connection
from tests.conftest import FakeLLMProvider


class _CapturingGraph:
    def __init__(self) -> None:
        self.state: AgentState | None = None

    async def ainvoke(self, state: AgentState) -> AgentState:
        self.state = AgentState(state)
        state["last_tool_result"] = None
        return state


@pytest.mark.anyio
async def test_submit_workflow_seeds_structured_request(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    graph = _CapturingGraph()
    runner = LangGraphRunner(
        provider=FakeLLMProvider(),
        conn=conn,
        bus=AsyncEventBus(),
        session_id="test",
    )
    runner._compiled = graph  # type: ignore[attr-defined]

    request = make_workflow_request("apply", {"url_or_text": "https://example.com/job"})
    result = await runner.submit_workflow(request)

    assert graph.state is not None
    assert graph.state["last_tool_result"] == {"workflow_request": request}
    assert result["last_tool_result"] is None
    conn.close()

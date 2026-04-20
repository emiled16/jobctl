"""Graph-grounded QA node with ``search_nodes`` and ``vector_search`` tools."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from jobctl.agent.prompts import SYSTEM_PROMPTS
from jobctl.agent.state import AgentState
from jobctl.core.events import (
    AgentDoneEvent,
    AgentToolCallEvent,
    AsyncEventBus,
)
from jobctl.llm.base import LLMProvider, Message, ToolCall, ToolSpec

logger = logging.getLogger(__name__)


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_nodes",
        description=(
            "Search the career graph by type and/or name substring. "
            "`type` is one of role, skill, project, company, education."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {
                    "type": "string",
                    "description": "Optional node type to filter by.",
                },
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="vector_search",
        description=(
            "Semantic search across node embeddings. Returns the most similar nodes to the query."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
        },
    ),
]


def _build_messages(state: AgentState) -> list[Message]:
    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPTS["graph_qa"]),
    ]
    for message in state.get("messages") or []:
        role = message.get("role")
        content = message.get("content")
        if role is None or content is None:
            continue
        messages.append(Message(role=role, content=content))
    return messages


def _run_tool(
    tool_call: ToolCall,
    conn: sqlite3.Connection,
    provider: LLMProvider,
) -> dict[str, Any]:
    name = tool_call.get("name", "")
    args = tool_call.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    if name == "search_nodes":
        from jobctl.db.graph import search_nodes as _search_nodes

        nodes = _search_nodes(
            conn,
            type=args.get("type"),
            name_contains=args.get("query"),
        )
        return {
            "results": [
                {
                    "id": node["id"],
                    "type": node["type"],
                    "name": node["name"],
                    "text": node.get("text_representation", ""),
                }
                for node in nodes[:20]
            ],
        }
    if name == "vector_search":
        query = str(args.get("query") or "")
        top_k = int(args.get("top_k") or 10)
        if not query:
            return {"results": []}
        try:
            embedding = provider.embed([query])[0]
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector_search embed failed: %s", exc)
            return {"error": str(exc), "results": []}
        from jobctl.db.vectors import search_similar as _search_similar

        hits = _search_similar(conn, embedding, top_k=top_k)
        return {"results": [{"node_id": node_id, "score": score} for node_id, score in hits]}

    return {"error": f"unknown tool: {name}"}


def graph_qa_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    bus: AsyncEventBus,
) -> AgentState:
    """Answer questions using graph + vector search tools."""
    messages = _build_messages(state)
    response = provider.chat(messages, tools=TOOL_SPECS)

    tool_calls = response.get("tool_calls") or []
    if tool_calls:
        for call in tool_calls:
            bus.publish(
                AgentToolCallEvent(
                    name=call.get("name", ""),
                    args=dict(call.get("arguments") or {}),
                )
            )
            result = _run_tool(call, conn, provider)
            messages.append(
                Message(
                    role="tool",
                    name=call.get("name", ""),
                    tool_call_id=call.get("id", ""),
                    content=json.dumps(result),
                )
            )
        response = provider.chat(messages)

    content = (response.get("content") or "").strip()
    bus.publish(AgentDoneEvent(role="assistant", content=content))

    state_messages = list(state.get("messages") or [])
    state_messages.append(Message(role="assistant", content=content))
    state["messages"] = state_messages
    return state


__all__ = ["TOOL_SPECS", "graph_qa_node"]

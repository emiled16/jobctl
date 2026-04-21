"""The ``curate_node`` generates curation proposals for review."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from jobctl.agent.state import AgentState
from jobctl.core.events import AgentDoneEvent, AgentTokenEvent, AsyncEventBus
from jobctl.curation.duplicates import find_duplicate_candidates
from jobctl.curation.proposals import CurationProposalStore
from jobctl.curation.rephrase import propose_rephrase
from jobctl.llm.base import LLMProvider, Message
from jobctl.llm.adapter import as_embedding_client
from jobctl.rag.store import VectorStore

logger = logging.getLogger(__name__)


_ORPHAN_TYPES = ("role", "position", "experience", "company")


def _find_orphan_roles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT nodes.id, nodes.name, nodes.type
        FROM nodes
        LEFT JOIN edges ON edges.source_id = nodes.id OR edges.target_id = nodes.id
        WHERE nodes.type IN (%s)
        GROUP BY nodes.id
        HAVING COUNT(edges.id) = 0
        LIMIT 10
        """
        % ",".join("?" * len(_ORPHAN_TYPES)),
        _ORPHAN_TYPES,
    ).fetchall()
    return [{"id": r[0], "name": r[1], "type": r[2]} for r in rows]


def _load_short_nodes(conn: sqlite3.Connection, max_len: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, type, name, text_representation
        FROM nodes
        WHERE text_representation IS NOT NULL
          AND LENGTH(text_representation) < ?
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (max_len,),
    ).fetchall()
    return [{"id": r[0], "type": r[1], "name": r[2], "text_representation": r[3]} for r in rows]


def _propose_new_connections(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, type, name, text_representation
        FROM nodes
        ORDER BY updated_at DESC
        LIMIT 40
        """
    ).fetchall()
    if len(rows) < 2:
        return []

    summary = "\n".join(f"- id={r[0]} type={r[1]} name={r[2]}" for r in rows)
    prompt = (
        "You are a knowledge-graph curator. Given the following nodes, "
        "propose up to "
        f"{limit} high-confidence new directed edges (source → relation → "
        "target) that are missing and factually supported. Return strict "
        'JSON: {"edges": [{"source_id":..,"target_id":..,'
        '"relation":..}]} with no prose.\n\n' + summary
    )
    try:
        reply = provider.chat(
            [
                Message(role="system", content="Return strict JSON only."),
                Message(role="user", content=prompt),
            ]
        )
    except Exception:
        return []

    import json

    try:
        data = json.loads(reply.get("content") or "{}")
    except Exception:
        return []
    edges = data.get("edges")
    if not isinstance(edges, list):
        return []
    return edges[:limit]


def curate_node(
    state: AgentState,
    *,
    provider: LLMProvider,
    conn: sqlite3.Connection,
    proposal_store: CurationProposalStore,
    bus: AsyncEventBus,
    vector_store: VectorStore,
) -> AgentState:
    """Generate curation proposals and publish a summary to ``bus``."""

    counts = {"merge": 0, "rephrase": 0, "connect": 0, "prune": 0, "orphans": 0}

    try:
        for candidate in find_duplicate_candidates(
            conn,
            vector_store,
            as_embedding_client(provider),
        ):
            proposal_store.create_proposal(
                "merge",
                {
                    "node_a_id": candidate.node_a["id"],
                    "node_b_id": candidate.node_b["id"],
                    "merged_name": candidate.node_a["name"],
                    "merged_text": candidate.node_a["text_representation"]
                    or candidate.node_b["text_representation"]
                    or "",
                    "cosine_similarity": candidate.cosine_similarity,
                    "name_similarity": candidate.name_similarity,
                    "reason": candidate.reason,
                },
            )
            counts["merge"] += 1
    except Exception:
        logger.exception("curate_node: duplicate detection failed")

    try:
        orphans = _find_orphan_roles(conn)
        counts["orphans"] = len(orphans)
        for orphan in orphans:
            question = (
                f"The {orphan['type']} '{orphan['name']}' has no related "
                "achievements or skills yet. What did you accomplish there?"
            )
            bus.publish(AgentTokenEvent(token=question + "\n"))
    except Exception:
        logger.exception("curate_node: orphan scan failed")

    try:
        for node in _load_short_nodes(conn):
            proposed = propose_rephrase(node, provider)
            if not proposed or proposed == node["text_representation"]:
                continue
            proposal_store.create_proposal(
                "rephrase",
                {
                    "node_id": node["id"],
                    "original_text": node["text_representation"],
                    "proposed_text": proposed,
                },
            )
            counts["rephrase"] += 1
    except Exception:
        logger.exception("curate_node: rephrase scan failed")

    try:
        for edge in _propose_new_connections(conn, provider):
            if not edge.get("source_id") or not edge.get("target_id"):
                continue
            proposal_store.create_proposal(
                "connect",
                {
                    "source_id": edge["source_id"],
                    "target_id": edge["target_id"],
                    "relation": edge.get("relation", "related_to"),
                },
            )
            counts["connect"] += 1
    except Exception:
        logger.exception("curate_node: connect proposals failed")

    summary = (
        f"Curation complete: {counts['merge']} merges, "
        f"{counts['rephrase']} rephrases, {counts['connect']} new edges, "
        f"{counts['orphans']} orphan follow-ups."
    )
    bus.publish(AgentDoneEvent(role="assistant", content=summary))

    messages = list(state.get("messages") or [])
    messages.append(Message(role="assistant", content=summary))
    state["messages"] = messages
    return state


__all__ = ["curate_node"]

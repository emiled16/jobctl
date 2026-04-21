from __future__ import annotations

from pathlib import Path

from jobctl.agent.nodes.refinement_node import refinement_node
from jobctl.agent.state import new_state, start_refinement_session
from jobctl.core.events import AsyncEventBus
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_node, get_node
from jobctl.ingestion.questions import RefinementQuestionStore
from jobctl.ingestion.schemas import RefinementQuestion
from jobctl.llm.schemas import ExtractedFact
from tests.conftest import FakeLLMProvider


def _question(source_ref: str, target_node_id: str) -> RefinementQuestion:
    return RefinementQuestion(
        source_ref=source_ref,
        target_node_id=target_node_id,
        category="metrics",
        prompt="What measurable impact can you confirm?",
        fact=ExtractedFact(
            entity_type="Achievement",
            entity_name="Latency",
            relation=None,
            related_to=None,
            properties={},
            text_representation="Improved latency",
        ),
        priority=100,
    )


def test_refinement_answer_shows_diff_before_applying(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    node_id = add_node(conn, "achievement", "Latency", {}, "Improved latency")
    store = RefinementQuestionStore(conn)
    question_id = store.create_question(_question("resume.md", node_id))
    state = start_refinement_session(new_state("test"), [question_id], source_ref="resume.md")
    state["messages"] = [{"role": "user", "content": "Reduced p95 latency by 40%"}]

    result = refinement_node(
        state,
        provider=FakeLLMProvider(chat_reply="not json", embedding_dimensions=1536),
        conn=conn,
        bus=AsyncEventBus(),
    )

    node = get_node(conn, node_id)
    assert node["properties"] == {}
    assert node["text_representation"] == "Improved latency"
    assert result["refinement_session"]["pending_update_plan"]
    assert "```diff" in result["messages"][-1]["content"]
    assert "Reply `accept` to apply" in result["messages"][-1]["content"]

    conn.close()


def test_refinement_accept_applies_reviewed_diff(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    node_id = add_node(conn, "achievement", "Latency", {}, "Improved latency")
    store = RefinementQuestionStore(conn)
    question_id = store.create_question(_question("resume.md", node_id))
    state = start_refinement_session(new_state("test"), [question_id], source_ref="resume.md")
    state["messages"] = [{"role": "user", "content": "Reduced p95 latency by 40%"}]
    provider = FakeLLMProvider(chat_reply="not json", embedding_dimensions=1536)

    review_state = refinement_node(state, provider=provider, conn=conn, bus=AsyncEventBus())
    review_state["messages"] = [
        *list(review_state.get("messages") or []),
        {"role": "user", "content": "accept"},
    ]
    result = refinement_node(review_state, provider=provider, conn=conn, bus=AsyncEventBus())

    node = get_node(conn, node_id)
    assert node["properties"]["confirmed_impact"] == "Reduced p95 latency by 40%"
    assert "Reduced p95 latency by 40%" in node["text_representation"]
    assert result["refinement_session"] is None
    stored = store.get(question_id)
    assert stored is not None
    assert stored.status == "converted_to_update"

    conn.close()


def test_refinement_reject_discards_reviewed_diff(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / ".jobctl.db")
    node_id = add_node(conn, "achievement", "Latency", {}, "Improved latency")
    store = RefinementQuestionStore(conn)
    question_id = store.create_question(_question("resume.md", node_id))
    state = start_refinement_session(new_state("test"), [question_id], source_ref="resume.md")
    state["messages"] = [{"role": "user", "content": "Reduced p95 latency by 40%"}]
    provider = FakeLLMProvider(chat_reply="not json", embedding_dimensions=1536)

    review_state = refinement_node(state, provider=provider, conn=conn, bus=AsyncEventBus())
    review_state["messages"] = [
        *list(review_state.get("messages") or []),
        {"role": "user", "content": "reject"},
    ]
    result = refinement_node(review_state, provider=provider, conn=conn, bus=AsyncEventBus())

    node = get_node(conn, node_id)
    assert node["properties"] == {}
    assert node["text_representation"] == "Improved latency"
    assert result["refinement_session"] is None
    stored = store.get(question_id)
    assert stored is not None
    assert stored.status == "skipped"

    conn.close()

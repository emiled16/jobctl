from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jobctl.curation.apply import apply_proposal
from jobctl.curation.proposals import CurationProposalStore
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_node, get_edges_from, get_node, get_nodes_by_type, search_nodes
from jobctl.ingestion.questions import RefinementQuestionStore
from jobctl.ingestion.reconcile import find_candidate_nodes_for_fact, reconcile_resume_facts
from jobctl.ingestion.refinement import persist_refinement_questions, plan_refinement_questions
from jobctl.ingestion.resume import (
    infer_resume_edges,
    normalize_resume_edges,
    normalize_resume_relation,
    persist_reconciled_resume_facts,
    promote_resume_skill_nodes,
)
from jobctl.ingestion.schemas import (
    FactReconciliation,
    RefinementQuestion,
    ResumeReconciliationResult,
)
from jobctl.llm.schemas import ExtractedFact


class FakeLLMClient:
    def __init__(self) -> None:
        self.embedded_texts: list[str] = []

    def get_embedding(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [0.0] * 1536


class FailingEmbeddingClient(FakeLLMClient):
    def get_embedding(self, text: str) -> list[float]:
        raise RuntimeError("invalid embedding model")


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def fact(
    entity_type: str = "Skill",
    entity_name: str = "Python",
    text: str = "Python skill",
    relation: str | None = None,
    related_to: str | None = None,
) -> ExtractedFact:
    return ExtractedFact(
        entity_type=entity_type,
        entity_name=entity_name,
        relation=relation,
        related_to=related_to,
        properties={},
        text_representation=text,
    )


def test_candidate_matching_and_fast_path_duplicate(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    add_node(conn, "skill", "Python", {}, "Python skill")

    resume_fact = fact()
    candidates = find_candidate_nodes_for_fact(
        conn,
        resume_fact,
        FakeLLMClient(),
        vector_store=fake_vector_store,
    )
    result = reconcile_resume_facts(
        conn,
        [resume_fact],
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )

    assert candidates[0].name == "Python"
    assert result.facts[0].classification == "duplicate"
    assert result.summary_counts["duplicate"] == 1


def test_no_candidate_fast_path_new(conn: sqlite3.Connection, fake_vector_store) -> None:
    result = reconcile_resume_facts(
        conn,
        [fact(entity_name="Go", text="Go skill")],
        None,
        "r.md",
        vector_store=fake_vector_store,
    )

    assert result.facts[0].classification == "new"
    assert result.summary_counts["new"] == 1


def test_persist_reconciled_facts_skips_duplicates_and_adds_new_once(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    role_id = add_node(conn, "role", "Staff Engineer", {}, "Staff Engineer role")
    duplicate = FactReconciliation(
        source_fact=fact(),
        classification="duplicate",
        confidence=0.99,
        matched_node_ids=[role_id],
    )
    new_fact = fact(
        entity_type="Skill",
        entity_name="Python",
        text="Python skill",
        relation="used_skill",
        related_to="Staff Engineer",
    )
    reconciliation = ResumeReconciliationResult(
        source_ref="resume.md",
        facts=[
            duplicate,
            FactReconciliation(source_fact=new_fact, classification="new", confidence=0.95),
        ],
    )

    summary = persist_reconciled_resume_facts(
        conn,
        reconciliation,
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )
    summary_again = persist_reconciled_resume_facts(
        conn,
        reconciliation,
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )

    assert summary["duplicates"] == 1
    assert summary["added"] == 1
    assert summary_again["added"] == 0
    assert len(get_nodes_by_type(conn, "skill")) == 1
    assert len(get_edges_from(conn, role_id)) == 1


def test_persist_reconciled_facts_does_not_fail_when_embedding_fails(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    reconciliation = ResumeReconciliationResult(
        source_ref="resume.md",
        facts=[
            FactReconciliation(
                source_fact=fact(entity_name="Python", text="Python skill"),
                classification="new",
                confidence=0.95,
            )
        ],
    )

    summary = persist_reconciled_resume_facts(
        conn,
        reconciliation,
        FailingEmbeddingClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )

    assert summary["added"] == 1
    assert len(get_nodes_by_type(conn, "skill")) == 1


def test_update_classification_creates_update_fact_proposal(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    node_id = add_node(conn, "achievement", "Reduced latency", {}, "Reduced latency")
    store = CurationProposalStore(conn)
    reconciliation = ResumeReconciliationResult(
        source_ref="resume.md",
        facts=[
            FactReconciliation(
                source_fact=fact(
                    entity_type="Achievement",
                    entity_name="Reduced latency",
                    text="Reduced latency by 40%",
                ),
                classification="update",
                confidence=0.88,
                matched_node_ids=[node_id],
                reason="Additive metric.",
                requires_confirmation=True,
            )
        ],
    )

    persist_reconciled_resume_facts(
        conn,
        reconciliation,
        FakeLLMClient(),
        "resume.md",
        proposal_store=store,
        vector_store=fake_vector_store,
    )
    proposals = store.list_pending("update_fact")

    assert len(proposals) == 1
    assert proposals[0].payload["node_id"] == node_id


def test_apply_update_fact_merges_properties_and_source(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    node_id = add_node(conn, "achievement", "Latency", {"stack": ["api"]}, "Latency work")

    apply_proposal(
        conn,
        "update_fact",
        {
            "node_id": node_id,
            "proposed_text": "Reduced latency by 40%",
            "proposed_properties": {"metrics": ["40%"], "stack": ["api", "cache"]},
            "source_ref": "resume.md",
        },
        fake_vector_store,
    )

    node = get_node(conn, node_id)
    assert node["properties"]["metrics"] == ["40%"]
    assert node["properties"]["stack"] == ["api", "cache"]
    assert "Reduced latency by 40%" in node["text_representation"]


def test_refinement_question_storage_lifecycle(conn: sqlite3.Connection) -> None:
    store = RefinementQuestionStore(conn)
    question = RefinementQuestion(
        source_ref="resume.md",
        category="metrics",
        prompt="What measurable impact can you confirm?",
        fact=fact(entity_type="Achievement", entity_name="Latency", text="Improved latency"),
        priority=100,
    )

    first_id = store.create_question(question)
    second_id = store.create_question(question)
    pending = store.list_pending(source_ref="resume.md")

    assert first_id == second_id
    assert len(pending) == 1

    store.mark_answered(first_id, "40% lower p95 latency")
    assert store.list_pending(source_ref="resume.md") == []
    answered = store.get(first_id)
    assert answered is not None
    assert answered.status == "answered"
    assert answered.answer_text == "40% lower p95 latency"


def test_refinement_planner_caps_and_persists_questions(conn: sqlite3.Connection) -> None:
    reconciliation = ResumeReconciliationResult(
        source_ref="resume.md",
        facts=[
            FactReconciliation(
                source_fact=fact(
                    entity_type="Achievement", entity_name=f"Impact {index}", text="Improved system"
                ),
                classification="new",
                confidence=0.9,
            )
            for index in range(5)
        ],
    )

    planned = plan_refinement_questions(conn, reconciliation, None, max_questions=3)
    ids = persist_refinement_questions(RefinementQuestionStore(conn), planned)

    assert len(planned) == 3
    assert len(ids) == 3


def test_infer_resume_edges_links_relationless_resume_nodes(conn: sqlite3.Connection) -> None:
    person_id = add_node(conn, "person", "Emile Dimas", {}, "Emile Dimas")
    role_id = add_node(
        conn,
        "role",
        "Machine Learning Engineer",
        {"source_context": "Machine Learning Engineer - MAXA AI | 2022 - Present"},
        "Machine Learning Engineer at MAXA AI",
    )
    company_id = add_node(conn, "company", "MAXA AI", {}, "MAXA AI employed Emile Dimas")
    achievement_id = add_node(
        conn,
        "achievement",
        "Snowflake-native ML platform",
        {"source_context": "MAXA AI experience bullet point"},
        "Built a Snowflake-native ML platform at MAXA AI",
    )

    added = infer_resume_edges(conn)

    assert added == 3
    assert {
        (edge["source_id"], edge["target_id"], edge["relation"])
        for edge in get_edges_from(conn, person_id)
    } == {(person_id, role_id, "held_role")}
    assert {
        (edge["source_id"], edge["target_id"], edge["relation"])
        for edge in get_edges_from(conn, role_id)
    } == {
        (role_id, company_id, "worked_at"),
        (role_id, achievement_id, "achieved"),
    }


def test_promote_resume_skill_nodes_creates_skills_from_nested_properties(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    project_id = add_node(
        conn,
        "project",
        "Agent platform",
        {
            "frameworks": ["LangChain", "LangGraph"],
            "cloud": "GCP",
            "deployment": ["GKE", "GitHub Actions"],
        },
        "Built an agent platform with LangChain and LangGraph on GCP",
    )
    add_node(conn, "skill", "GCP", {}, "GCP")

    summary = promote_resume_skill_nodes(
        conn,
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )

    skills = {node["name"] for node in get_nodes_by_type(conn, "skill")}
    assert summary == {"skills_created": 4, "skill_edges_added": 5}
    assert skills == {"GCP", "GKE", "GitHub Actions", "LangChain", "LangGraph"}
    edges = get_edges_from(conn, project_id)
    assert {edge["relation"] for edge in edges} == {"used_skill"}
    assert {edge["target"]["name"] for edge in edges} == skills


def test_promote_resume_skill_nodes_is_idempotent(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    add_node(
        conn,
        "achievement",
        "Distributed pipelines",
        {"technology": "PySpark"},
        "Built distributed PySpark pipelines",
    )

    first = promote_resume_skill_nodes(
        conn,
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )
    second = promote_resume_skill_nodes(
        conn,
        FakeLLMClient(),
        "resume.md",
        vector_store=fake_vector_store,
    )

    assert first == {"skills_created": 1, "skill_edges_added": 1}
    assert second == {"skills_created": 0, "skill_edges_added": 0}
    assert [node["name"] for node in search_nodes(conn, type="skill")] == ["PySpark"]


def test_normalize_resume_relation_variants() -> None:
    assert normalize_resume_relation("used_in", "skill") == "used_skill"
    assert normalize_resume_relation("built-at", "project") == "worked_at"
    assert normalize_resume_relation("published_in", "publication") == "authored"
    assert normalize_resume_relation("related_to", "skill") == "used_skill"


def test_normalize_resume_edges_updates_existing_edge_labels(conn: sqlite3.Connection) -> None:
    source_id = add_node(conn, "project", "Platform", {}, "Platform")
    target_id = add_node(conn, "skill", "LangGraph", {}, "LangGraph")
    conn.execute(
        """
        INSERT INTO edges (id, source_id, target_id, relation, properties, created_at)
        VALUES ('edge-1', ?, ?, 'used_in', '{}', 'now')
        """,
        (source_id, target_id),
    )
    conn.commit()

    assert normalize_resume_edges(conn) == 1

    edges = get_edges_from(conn, source_id)
    assert edges[0]["relation"] == "used_skill"

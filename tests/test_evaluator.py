import sqlite3
from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import add_edge, add_node
from jobctl.db.vectors import EMBEDDING_DIMENSIONS
from jobctl.jobs import evaluator
from jobctl.jobs.evaluator import display_evaluation, evaluate_fit, retrieve_relevant_experience
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


class FakeLLMClient:
    def __init__(self) -> None:
        self.embedding_texts: list[str] = []
        self.structured_messages: list[list[dict]] = []

    def get_embedding(self, text: str) -> list[float]:
        self.embedding_texts.append(text)
        return make_embedding(0.1)

    def chat_structured(self, messages: list[dict], response_format: type) -> FitEvaluation:
        self.structured_messages.append(messages)
        assert response_format is FitEvaluation
        return FitEvaluation(
            score=8.0,
            matching_strengths=["Built Python systems at Acme"],
            gaps=["No explicit Kubernetes evidence"],
            recommendations=["Lead with Python platform work"],
            summary="Strong fit with one infrastructure gap.",
        )


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_retrieve_relevant_experience_merges_matching_subgraphs(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role_id = add_node(conn, "role", "Senior Engineer", {}, "Built Python platforms")
    skill_id = add_node(conn, "skill", "Python", {}, "Python engineering")
    add_node(conn, "skill", "Design", {}, "Product design")
    add_edge(conn, role_id, skill_id, "used_skill", {})
    monkeypatch.setattr(
        evaluator,
        "search_similar",
        lambda _conn, _embedding, top_k: [(role_id, 0.0), (skill_id, 0.1)],
    )
    jd = make_jd()
    llm_client = FakeLLMClient()

    relevant_experience = retrieve_relevant_experience(conn, jd, llm_client)

    assert llm_client.embedding_texts == ["Python\nBuild backend systems"]
    assert {node["id"] for node in relevant_experience["nodes"]} == {role_id, skill_id}
    assert [(edge["source_id"], edge["target_id"]) for edge in relevant_experience["edges"]] == [
        (role_id, skill_id)
    ]


def test_evaluate_fit_prompts_with_jd_and_graph_context() -> None:
    llm_client = FakeLLMClient()
    jd = make_jd()
    relevant_experience = {
        "nodes": [
            {
                "id": "node-1",
                "type": "role",
                "name": "Senior Engineer",
                "properties": {},
                "text_representation": "Built Python systems at Acme",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "edges": [],
    }

    evaluation = evaluate_fit(jd, relevant_experience, llm_client)

    prompt = llm_client.structured_messages[0][1]["content"]
    assert evaluation.score == 8.0
    assert "title: Senior Engineer" in prompt
    assert "node-1: role named Senior Engineer" in prompt
    assert "Return a concise fit evaluation" in prompt


def test_display_evaluation_prints_rich_summary(capsys: pytest.CaptureFixture[str]) -> None:
    display_evaluation(
        make_jd(),
        FitEvaluation(
            score=7.5,
            matching_strengths=["Python systems"],
            gaps=["No Rails evidence"],
            recommendations=["Emphasize backend work"],
            summary="Clear fit.",
        ),
    )

    captured = capsys.readouterr().out
    assert "Senior Engineer @ Acme" in captured
    assert "Score: 7.5/10" in captured
    assert "Python systems" in captured
    assert "Clear fit." in captured


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build backend systems"],
        qualifications=["5 years"],
        nice_to_haves=["SQLite"],
        raw_text="Senior Engineer role",
    )


def make_embedding(first_value: float) -> list[float]:
    embedding = [0.0] * EMBEDDING_DIMENSIONS
    embedding[0] = first_value
    return embedding

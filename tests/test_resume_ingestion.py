import sqlite3
from pathlib import Path

import pytest

from jobctl.db.connection import get_connection
from jobctl.db.graph import get_edges_from, get_nodes_by_type
from jobctl.ingestion.resume import (
    UnsupportedFormatError,
    extract_facts_from_resume,
    persist_facts,
    read_resume,
)
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile


class FakeLLMClient:
    def __init__(self, profile: ExtractedProfile | None = None) -> None:
        self.profile = profile or ExtractedProfile(facts=[])
        self.embedded_texts: list[str] = []
        self.structured_messages: list[list[dict]] = []

    def get_embedding(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [0.0] * 1536

    def chat_structured(self, messages: list[dict], response_format: type) -> ExtractedProfile:
        self.structured_messages.append(messages)
        assert response_format is ExtractedProfile
        return self.profile


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


def test_read_resume_plain_text(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.md"
    resume_path.write_text("# Resume\nPython engineer", encoding="utf-8")

    assert read_resume(resume_path) == "# Resume\nPython engineer"


def test_read_resume_rejects_unknown_extension(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.rtf"
    resume_path.write_text("unsupported", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        read_resume(resume_path)


def test_extract_facts_from_resume_uses_structured_profile_schema() -> None:
    profile = ExtractedProfile(
        facts=[
            ExtractedFact(
                entity_type="skill",
                entity_name="Python",
                relation=None,
                related_to=None,
                properties={},
                text_representation="Python",
            )
        ]
    )
    llm_client = FakeLLMClient(profile)

    result = extract_facts_from_resume("Python engineer", llm_client)

    assert result == profile
    assert "Python engineer" in llm_client.structured_messages[0][1]["content"]
    system_prompt = llm_client.structured_messages[0][0]["content"]
    assert "entity_type" in system_prompt
    assert "entity_name" in system_prompt
    assert "text_representation" in system_prompt
    assert "Do not use legacy keys like type, name" in system_prompt


def test_persist_facts_creates_nodes_edges_and_embeddings(
    conn: sqlite3.Connection,
    fake_vector_store,
) -> None:
    facts = [
        ExtractedFact(
            entity_type="Role",
            entity_name="Staff Engineer",
            relation=None,
            related_to=None,
            properties={"start_date": "2024-01"},
            text_representation="Staff Engineer role",
        ),
        ExtractedFact(
            entity_type="Skill",
            entity_name="Python",
            relation="used_skill",
            related_to="Staff Engineer",
            properties={},
            text_representation="Python skill",
        ),
        ExtractedFact(
            entity_type="Achievement",
            entity_name="Reduced latency",
            relation="achieved",
            related_to="Staff Engineer",
            properties={"metric": "40%"},
            text_representation="Reduced latency by 40%",
        ),
        ExtractedFact(
            entity_type="Education",
            entity_name="University",
            relation=None,
            related_to=None,
            properties={},
            text_representation="University education",
        ),
    ]
    llm_client = FakeLLMClient()

    persisted_count = persist_facts(
        conn,
        facts,
        llm_client,
        interactive=False,
        vector_store=fake_vector_store,
    )

    roles = get_nodes_by_type(conn, "role")
    role_edges = get_edges_from(conn, roles[0]["id"])
    assert persisted_count == 4
    assert len(roles) == 1
    assert {edge["relation"] for edge in role_edges} == {"used_skill", "achieved"}
    assert len(llm_client.embedded_texts) == 4

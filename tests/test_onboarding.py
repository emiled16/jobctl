from pathlib import Path

from jobctl.conversation.onboard import analyze_coverage, generate_followup
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_edge, add_node


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        self.messages.append(messages)
        return "What impact did you have in the Staff Engineer role?"


def test_analyze_coverage_reports_missing_sections() -> None:
    conn = get_connection(Path(":memory:"))
    try:
        coverage = analyze_coverage(conn)
    finally:
        conn.close()

    assert coverage["roles_count"] == 0
    assert coverage["has_education"] is False
    assert coverage["missing_sections"] == [
        "roles",
        "education",
        "skills",
        "achievements",
        "stories",
    ]


def test_analyze_coverage_finds_roles_missing_edges() -> None:
    conn = get_connection(Path(":memory:"))
    try:
        role_id = add_node(conn, "role", "Staff Engineer", {}, "Staff Engineer")
        skill_id = add_node(conn, "skill", "Python", {}, "Python")
        achievement_id = add_node(conn, "achievement", "Reduced latency", {}, "Reduced latency")
        add_node(conn, "education", "University", {}, "University")
        add_node(conn, "story", "Incident response", {}, "Incident response")
        add_edge(conn, role_id, skill_id, "used_skill", {})
        add_edge(conn, role_id, achievement_id, "achieved", {})

        coverage = analyze_coverage(conn)
    finally:
        conn.close()

    assert coverage["roles_count"] == 1
    assert coverage["skills_count"] == 1
    assert coverage["achievements_count"] == 1
    assert coverage["roles_without_achievements"] == []
    assert coverage["roles_without_skills"] == []
    assert coverage["missing_sections"] == []


def test_generate_followup_includes_coverage_and_nodes() -> None:
    conn = get_connection(Path(":memory:"))
    llm_client = FakeLLMClient()
    try:
        add_node(conn, "role", "Staff Engineer", {}, "Staff Engineer")

        question = generate_followup(conn, llm_client, analyze_coverage(conn))
    finally:
        conn.close()

    assert question == "What impact did you have in the Staff Engineer role?"
    assert "Staff Engineer" in llm_client.messages[0][1]["content"]

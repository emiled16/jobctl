import sqlite3
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from jobctl.config import JobctlConfig
from jobctl.conversation.agent import AgentShell
from jobctl.db.connection import get_connection
from jobctl.db.graph import add_edge, add_node, get_nodes_by_type
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        self.messages.append(messages)
        return "Graph-grounded answer."

    def chat_structured(self, messages: list[dict], response_format: type) -> ExtractedProfile:
        self.messages.append(messages)
        assert response_format is ExtractedProfile
        return ExtractedProfile(
            facts=[
                ExtractedFact(
                    entity_type="Skill",
                    entity_name="Python",
                    relation=None,
                    related_to=None,
                    properties={},
                    text_representation="Python programming",
                )
            ]
        )

    def get_embedding(self, text: str) -> list[float]:
        return [0.0] * 1536


@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = get_connection(Path(":memory:"))
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def shell(conn: sqlite3.Connection) -> tuple[AgentShell, StringIO, FakeLLMClient]:
    output = StringIO()
    llm_client = FakeLLMClient()
    console = Console(file=output, force_terminal=False, width=120)
    config = JobctlConfig(
        openai_api_key="",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        llm_model="gpt-5.4",
        default_template="resume.html",
    )
    return AgentShell(conn, llm_client, config, Path.cwd(), console), output, llm_client


def test_agent_shell_help_lists_commands(
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/help") is True

    rendered = output.getvalue()
    assert "/ingest" in rendered
    assert "/graph" in rendered
    assert "/report" in rendered


def test_agent_shell_renders_graph(
    conn: sqlite3.Connection,
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    role_id = add_node(conn, "role", "Backend Engineer", {}, "Built APIs")
    skill_id = add_node(conn, "skill", "Python", {}, "Python")
    add_edge(conn, role_id, skill_id, "used_skill", {})
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/graph") is True

    rendered = output.getvalue()
    assert "Knowledge Graph" in rendered
    assert "Backend Engineer" in rendered
    assert "used_skill -> Python (skill)" in rendered


def test_agent_shell_renders_coverage_report(
    conn: sqlite3.Connection,
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    add_node(conn, "role", "Backend Engineer", {}, "Built APIs")
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/report coverage") is True

    rendered = output.getvalue()
    assert "Coverage" in rendered
    assert "Missing sections" in rendered
    assert "education, skills, achievements, stories" in rendered
    assert "Backend Engineer" in rendered


def test_agent_shell_switches_mode(
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/mode onboard") is True

    assert agent_shell.mode == "onboard"
    assert "Mode switched to onboard." in output.getvalue()


def test_agent_shell_onboard_mode_persists_plain_text(
    conn: sqlite3.Connection,
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/mode onboard") is True
    assert agent_shell.execute("I use Python for data pipelines.") is True
    assert agent_shell.execute("done") is True

    assert get_nodes_by_type(conn, "skill")[0]["name"] == "Python"
    assert "Saved profile facts: 1" in output.getvalue()
    assert agent_shell.mode == "explore"


def test_agent_shell_asks_with_graph_context(
    conn: sqlite3.Connection,
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    add_node(conn, "skill", "Python", {}, "Python programming")
    agent_shell, output, llm_client = shell

    assert agent_shell.execute("/ask What should I emphasize?") is True

    assert "Graph-grounded answer." in output.getvalue()
    prompt = llm_client.messages[0][1]["content"]
    assert "Python programming" in prompt
    assert "What should I emphasize?" in prompt


def test_agent_shell_exit_returns_false(
    shell: tuple[AgentShell, StringIO, FakeLLMClient],
) -> None:
    agent_shell, output, _llm_client = shell

    assert agent_shell.execute("/exit") is False
    assert "Leaving jobctl agent." in output.getvalue()

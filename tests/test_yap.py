import sqlite3
from pathlib import Path

from click.testing import CliRunner

from jobctl.cli import main
from jobctl.conversation import yap
from jobctl.db.connection import get_connection
from jobctl.db.graph import get_nodes_by_type
from jobctl.llm.schemas import ExtractedFact, ProposedFact, ProposedFacts


class FakeLLMClient:
    def __init__(self) -> None:
        self.structured_messages: list[list[dict]] = []
        self.chat_messages: list[list[dict]] = []
        self.embedded_texts: list[str] = []

    def chat_structured(self, messages: list[dict], response_format: type) -> ProposedFacts:
        self.structured_messages.append(messages)
        assert response_format is ProposedFacts
        return ProposedFacts(
            facts=[
                ProposedFact(
                    fact=ExtractedFact(
                        entity_type="skill",
                        entity_name="Python",
                        relation=None,
                        related_to=None,
                        properties={"years": 8},
                        text_representation="Python programming",
                    ),
                    confidence=0.91,
                    source_quote="I used Python for eight years.",
                )
            ]
        )

    def chat(self, messages: list[dict], temperature: float = 0.7) -> str:
        self.chat_messages.append(messages)
        return "What did you build with Python?"

    def get_embedding(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        return [0.0] * 1536


def test_extract_proposed_facts_uses_existing_context() -> None:
    llm_client = FakeLLMClient()

    proposed_facts = yap.extract_proposed_facts(
        "I used Python for eight years.",
        "skill: SQL",
        llm_client,
    )

    assert proposed_facts[0].fact.entity_name == "Python"
    prompt = llm_client.structured_messages[0][1]["content"]
    assert "skill: SQL" in prompt
    assert "I used Python for eight years." in prompt


def test_run_yap_persists_confirmed_facts(
    monkeypatch,
    capsys,
) -> None:
    conn = get_connection(Path(":memory:"))
    llm_client = FakeLLMClient()
    inputs = iter(["I used Python for eight years.", "done"])
    monkeypatch.setattr(yap, "_read_multiline_input", lambda: next(inputs))
    monkeypatch.setattr(
        yap,
        "_confirm_proposed_facts",
        lambda proposed_facts: [proposed_facts[0].fact],
    )

    try:
        yap.run_yap(conn, llm_client)
        nodes = get_nodes_by_type(conn, "skill")
    finally:
        conn.close()

    assert nodes[0]["name"] == "Python"
    assert llm_client.embedded_texts == ["Python programming"]
    assert "Added 1 facts" in capsys.readouterr().out


def test_yap_cli_opens_project_and_runs_loop(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    calls: list[sqlite3.Connection] = []

    def fake_run_yap(conn: sqlite3.Connection, _llm_client) -> None:
        calls.append(conn)

    monkeypatch.setattr(yap, "run_yap", fake_run_yap)

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        runner.invoke(main, ["init"], catch_exceptions=False)
        result = runner.invoke(main, ["yap"], catch_exceptions=False)

        assert result.exit_code == 0
        assert calls
        assert (Path(isolated_dir) / ".jobctl" / "jobctl.db").exists()

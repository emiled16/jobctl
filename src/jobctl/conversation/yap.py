"""Freeform profile update conversation logic."""

import os
import shlex
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from jobctl.ingestion.resume import persist_facts
from jobctl.llm.schemas import ExtractedFact, ProposedFact, ProposedFacts


console = Console()
MAX_CONTEXT_CHARS = 6000


def extract_proposed_facts(text: str, existing_context: str, llm_client) -> list[ProposedFact]:
    messages = [
        {
            "role": "system",
            "content": (
                "Extract new factual claims about the user's professional experience. "
                "Return proposed facts only when the text contains concrete career data. "
                "For each proposal include the extracted fact, a confidence score from 0 to 1, "
                "and the exact source quote that supports it."
            ),
        },
        {
            "role": "user",
            "content": f"Existing graph context:\n{existing_context}\n\nUser text:\n{text}",
        },
    ]
    return llm_client.chat_structured(messages, response_format=ProposedFacts).facts


def run_yap(conn: sqlite3.Connection, llm_client) -> None:
    console.print(
        "Talk about your experience. The AI will extract facts. Type `done` to exit. "
        "Submit a blank line to process each entry."
    )
    facts_added = 0

    while True:
        text = _read_multiline_input()
        if text.strip().lower() == "done":
            break
        if not text.strip():
            continue

        proposed_facts = extract_proposed_facts(text, _existing_context(conn), llm_client)
        accepted_facts = _confirm_proposed_facts(proposed_facts)
        if accepted_facts:
            facts_added += persist_facts(conn, accepted_facts, llm_client, interactive=False)

        acknowledgment = _generate_acknowledgment(text, proposed_facts, llm_client)
        if acknowledgment:
            console.print(acknowledgment)

    console.print(f"Yap session complete. Added {facts_added} facts.")


def _read_multiline_input() -> str:
    lines: list[str] = []
    while True:
        line = console.input("> " if not lines else "")
        if not lines and line.strip().lower() == "done":
            return "done"
        if line == "":
            return "\n".join(lines)
        lines.append(line)


def _existing_context(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT type, name, text_representation
        FROM nodes
        ORDER BY updated_at DESC, name
        """
    ).fetchall()
    context_lines = [
        f"- {row['type']}: {row['name']} :: {row['text_representation']}" for row in rows
    ]
    context = "\n".join(context_lines)
    return context[:MAX_CONTEXT_CHARS]


def _confirm_proposed_facts(proposed_facts: list[ProposedFact]) -> list[ExtractedFact]:
    accepted_facts: list[ExtractedFact] = []
    for proposed_fact in proposed_facts:
        fact = proposed_fact.fact
        while True:
            console.print(_proposed_fact_panel(proposed_fact, fact))
            choice = Prompt.ask("Persist this fact?", choices=["y", "n", "e"], default="y").lower()
            if choice == "y":
                accepted_facts.append(fact)
                break
            if choice == "n":
                break
            edited_fact = _edit_fact(fact)
            if edited_fact is not None:
                fact = edited_fact
    return accepted_facts


def _proposed_fact_panel(proposed_fact: ProposedFact, fact: ExtractedFact) -> Panel:
    fact_yaml = yaml.safe_dump(fact.model_dump(), sort_keys=False)
    body = (
        f"Confidence: {proposed_fact.confidence:.2f}\n"
        f"Source quote: {proposed_fact.source_quote}\n\n"
        f"{fact_yaml}"
    )
    return Panel(Syntax(body, "yaml"), title=f"{fact.entity_type}: {fact.entity_name}")


def _edit_fact(fact: ExtractedFact) -> ExtractedFact | None:
    editor = os.environ.get("EDITOR")
    if not editor:
        console.print("Set $EDITOR to edit facts.")
        return None

    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(yaml.safe_dump(fact.model_dump(), sort_keys=False))

    try:
        subprocess.run([*shlex.split(editor), str(temp_path)], check=True)
        edited_data = yaml.safe_load(temp_path.read_text(encoding="utf-8"))
        return ExtractedFact.model_validate(edited_data)
    finally:
        temp_path.unlink(missing_ok=True)


def _generate_acknowledgment(text: str, proposed_facts: list[ProposedFact], llm_client) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Reply briefly and naturally. Acknowledge what the user shared and ask one "
                "useful follow-up question if more detail would improve their career profile."
            ),
        },
        {
            "role": "user",
            "content": f"User text:\n{text}\n\nExtracted proposed facts: {proposed_facts}",
        },
    ]
    return llm_client.chat(messages, temperature=0.5).strip()

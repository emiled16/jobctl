"""Resume file parsing and fact persistence."""

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

from jobctl.db.graph import add_edge, add_node, search_nodes
from jobctl.db.vectors import embed_node
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile


class UnsupportedFormatError(ValueError):
    """Raised when a resume file extension is not supported."""


console = Console()


def read_resume(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return _read_pdf(file_path)
    if suffix == ".docx":
        return _read_docx(file_path)
    raise UnsupportedFormatError(f"Unsupported resume format: {suffix or '<none>'}")


def extract_facts_from_resume(resume_text: str, llm_client) -> ExtractedProfile:
    messages = [
        {
            "role": "system",
            "content": (
                "Extract a career knowledge graph from the resume. Create facts for roles, "
                "companies, skills, achievements, education, and projects. Use relation and "
                "related_to when a fact should connect to another entity by name. Keep "
                "properties structured with dates, metrics, descriptions, and source context."
            ),
        },
        {"role": "user", "content": resume_text},
    ]
    return llm_client.chat_structured(messages, response_format=ExtractedProfile)


def persist_facts(
    conn: sqlite3.Connection,
    facts: list[ExtractedFact],
    llm_client,
    interactive: bool = True,
) -> int:
    persisted_count = 0
    for fact in facts:
        accepted_fact = _confirm_fact(fact) if interactive else fact
        if accepted_fact is None:
            continue

        entity_type = accepted_fact.entity_type.lower()
        node_id = add_node(
            conn,
            entity_type,
            accepted_fact.entity_name,
            accepted_fact.properties,
            accepted_fact.text_representation,
        )
        embed_node(conn, node_id, llm_client)

        related_node_id = _resolve_related_node(conn, accepted_fact, llm_client)
        if related_node_id is not None and accepted_fact.relation:
            source_id, target_id = _edge_direction(
                conn,
                node_id,
                related_node_id,
                accepted_fact.relation,
                entity_type,
            )
            add_edge(conn, source_id, target_id, accepted_fact.relation, {})

        persisted_count += 1

    return persisted_count


def _read_pdf(file_path: Path) -> str:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise UnsupportedFormatError("PDF resume parsing requires pymupdf") from exc

    with fitz.open(file_path) as document:
        return "\n".join(page.get_text() for page in document)


def _read_docx(file_path: Path) -> str:
    try:
        import docx
    except ModuleNotFoundError as exc:
        raise UnsupportedFormatError("DOCX resume parsing requires python-docx") from exc

    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)


def _confirm_fact(fact: ExtractedFact) -> ExtractedFact | None:
    while True:
        console.print(_fact_panel(fact))
        choice = Prompt.ask("Persist this fact?", choices=["y", "n", "e"], default="y").lower()
        if choice == "y":
            return fact
        if choice == "n":
            return None
        edited_fact = _edit_fact(fact)
        if edited_fact is not None:
            fact = edited_fact


def _fact_panel(fact: ExtractedFact) -> Panel:
    fact_yaml = yaml.safe_dump(fact.model_dump(), sort_keys=False)
    return Panel(Syntax(fact_yaml, "yaml"), title=f"{fact.entity_type}: {fact.entity_name}")


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


def _resolve_related_node(conn: sqlite3.Connection, fact: ExtractedFact, llm_client) -> str | None:
    if not fact.related_to:
        return None

    matches = search_nodes(conn, name_contains=fact.related_to)
    exact_matches = [node for node in matches if node["name"].lower() == fact.related_to.lower()]
    if exact_matches:
        return exact_matches[0]["id"]

    related_node_id = add_node(conn, "unknown", fact.related_to, {}, fact.related_to)
    embed_node(conn, related_node_id, llm_client)
    return related_node_id


def _edge_direction(
    conn: sqlite3.Connection,
    node_id: str,
    related_node_id: str,
    relation: str,
    entity_type: str,
) -> tuple[str, str]:
    if relation in {"used_skill", "achieved", "worked_at"} and entity_type != "role":
        related_type = conn.execute(
            "SELECT type FROM nodes WHERE id = ?",
            (related_node_id,),
        ).fetchone()["type"]
        if related_type == "role":
            return related_node_id, node_id
    return node_id, related_node_id

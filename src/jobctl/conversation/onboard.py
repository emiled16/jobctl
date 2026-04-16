"""Onboarding conversation logic."""

import sqlite3
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, Prompt

from jobctl.ingestion.github import ingest_github
from jobctl.ingestion.resume import extract_facts_from_resume, persist_facts, read_resume
from jobctl.llm.schemas import ExtractedProfile


console = Console()


def analyze_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    roles = _nodes_by_type(conn, "role")
    roles_without_achievements = _roles_missing_relation(conn, "achieved")
    roles_without_skills = _roles_missing_relation(conn, "used_skill")

    coverage = {
        "roles_count": len(roles),
        "has_education": _node_count(conn, "education") > 0,
        "skills_count": _node_count(conn, "skill"),
        "achievements_count": _node_count(conn, "achievement"),
        "roles_without_achievements": roles_without_achievements,
        "roles_without_skills": roles_without_skills,
        "has_stories": _node_count(conn, "story") > 0,
        "missing_sections": [],
    }
    coverage["missing_sections"] = _missing_sections(coverage)
    return coverage


def generate_followup(conn: sqlite3.Connection, llm_client, coverage: dict[str, Any]) -> str:
    nodes = conn.execute(
        """
        SELECT type, name
        FROM nodes
        ORDER BY type, name
        """
    ).fetchall()
    node_summary = [{"type": row["type"], "name": row["name"]} for row in nodes]
    messages = [
        {
            "role": "system",
            "content": (
                "Generate exactly one concise follow-up question to deepen a career profile. "
                "Prioritize roles missing achievements, then roles missing skills, then missing "
                "stories, education, and general profile depth."
            ),
        },
        {
            "role": "user",
            "content": f"Coverage: {coverage}\nExisting nodes: {node_summary}",
        },
    ]
    return llm_client.chat(messages, temperature=0.4).strip()


def run_onboarding(conn: sqlite3.Connection, llm_client, config) -> None:
    initial_nodes = _total_count(conn, "nodes")
    initial_edges = _total_count(conn, "edges")

    if Confirm.ask("Do you have a resume file to ingest?", default=True):
        resume_path = Path(Prompt.ask("Resume file path")).expanduser()
        resume_text = read_resume(resume_path)
        profile = extract_facts_from_resume(resume_text, llm_client)
        persist_facts(conn, profile.facts, llm_client, interactive=True)

    if Confirm.ask("Do you have GitHub repositories to ingest?", default=False):
        github_input = Prompt.ask("GitHub username or repository URLs, separated by commas")
        values = [value.strip() for value in github_input.split(",") if value.strip()]
        ingest_github(conn, values, llm_client, interactive=True)

    while True:
        coverage = analyze_coverage(conn)
        if _coverage_complete(coverage):
            break

        question = generate_followup(conn, llm_client, coverage)
        console.print(question)
        answer = Prompt.ask("Answer, or type done")
        if answer.strip().lower() == "done":
            break

        profile = llm_client.chat_structured(
            [
                {
                    "role": "system",
                    "content": "Extract career profile facts from the user's answer.",
                },
                {"role": "user", "content": answer},
            ],
            response_format=ExtractedProfile,
        )
        persist_facts(conn, profile.facts, llm_client, interactive=True)

    created_nodes = _total_count(conn, "nodes") - initial_nodes
    created_edges = _total_count(conn, "edges") - initial_edges
    final_coverage = analyze_coverage(conn)
    console.print(
        f"Onboarding complete. Created {created_nodes} nodes and {created_edges} edges. "
        f"Missing sections: {', '.join(final_coverage['missing_sections']) or 'none'}."
    )


def _node_count(conn: sqlite3.Connection, node_type: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM nodes WHERE type = ?", (node_type,)
    ).fetchone()
    return int(row["count"])


def _total_count(conn: sqlite3.Connection, table: str) -> int:
    if table not in {"nodes", "edges"}:
        raise ValueError(f"Unsupported count table: {table}")
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _nodes_by_type(conn: sqlite3.Connection, node_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM nodes
        WHERE type = ?
        ORDER BY name
        """,
        (node_type,),
    ).fetchall()
    return [dict(row) for row in rows]


def _roles_missing_relation(conn: sqlite3.Connection, relation: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT nodes.*
        FROM nodes
        WHERE nodes.type = 'role'
          AND NOT EXISTS (
              SELECT 1
              FROM edges
              WHERE edges.source_id = nodes.id
                AND edges.relation = ?
          )
        ORDER BY nodes.name
        """,
        (relation,),
    ).fetchall()
    return [dict(row) for row in rows]


def _missing_sections(coverage: dict[str, Any]) -> list[str]:
    missing_sections: list[str] = []
    if coverage["roles_count"] == 0:
        missing_sections.append("roles")
    if not coverage["has_education"]:
        missing_sections.append("education")
    if coverage["skills_count"] == 0:
        missing_sections.append("skills")
    if coverage["achievements_count"] == 0:
        missing_sections.append("achievements")
    if not coverage["has_stories"]:
        missing_sections.append("stories")
    return missing_sections


def _coverage_complete(coverage: dict[str, Any]) -> bool:
    return (
        not coverage["missing_sections"]
        and not coverage["roles_without_achievements"]
        and not coverage["roles_without_skills"]
    )

"""Job fit evaluation."""

import sqlite3
from typing import Protocol

import yaml
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from jobctl.db.graph import Edge, Node, get_subgraph
from jobctl.llm.schemas import ExtractedJD, FitEvaluation
from jobctl.rag.store import VectorStore


class FitEvaluationLLMClient(Protocol):
    def get_embedding(self, text: str) -> list[float]: ...

    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_format: type[FitEvaluation],
    ) -> FitEvaluation: ...


def retrieve_relevant_experience(
    conn: sqlite3.Connection,
    jd: ExtractedJD,
    llm_client: FitEvaluationLLMClient,
    vector_store: VectorStore,
) -> dict[str, list[Node] | list[Edge]]:
    """Retrieve graph context most relevant to a job description."""
    query_text = "\n".join([*jd.requirements, *jd.responsibilities]).strip()
    if not query_text:
        query_text = jd.raw_text

    query_embedding = llm_client.get_embedding(query_text)
    matches = vector_store.search(query_embedding, top_k=20)

    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    for hit in matches:
        subgraph = get_subgraph(conn, hit.node_id, depth=1)
        for node in subgraph["nodes"]:
            nodes[node["id"]] = node
        for edge in subgraph["edges"]:
            edges[edge["id"]] = edge

    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def evaluate_fit(
    jd: ExtractedJD,
    relevant_experience: dict[str, list[Node] | list[Edge]],
    llm_client: FitEvaluationLLMClient,
) -> FitEvaluation:
    """Evaluate candidate fit for a job description using retrieved graph facts."""
    jd_yaml = yaml.safe_dump(jd.model_dump(), sort_keys=False)
    experience_text = _format_relevant_experience(relevant_experience)
    messages = [
        {
            "role": "system",
            "content": (
                "You evaluate job fit from a candidate knowledge graph. "
                "Ground every strength in specific evidence from the graph. "
                "Use a 1-10 score where 10 means unusually strong fit."
            ),
        },
        {
            "role": "user",
            "content": (
                "Evaluate this candidate for the job description.\n\n"
                "Job description YAML:\n"
                f"{jd_yaml}\n"
                "Relevant candidate graph facts:\n"
                f"{experience_text}\n\n"
                "Return a concise fit evaluation with:\n"
                "- score from 1 to 10\n"
                "- matching strengths with specific graph evidence\n"
                "- gaps or risks\n"
                "- recommendations for positioning the application\n"
                "- a short summary paragraph"
            ),
        },
    ]
    return llm_client.chat_structured(messages, response_format=FitEvaluation)


def display_evaluation(jd: ExtractedJD, evaluation: FitEvaluation) -> None:
    """Print a Rich formatted job fit evaluation."""
    console = Console()
    title = f"{jd.title} @ {jd.company}"
    if jd.location:
        title = f"{title} ({jd.location})"

    score_style = _score_style(evaluation.score)
    content = Group(
        Text(f"Score: {evaluation.score:.1f}/10", style=f"bold {score_style}"),
        Text(""),
        _bullet_section("Strengths", evaluation.matching_strengths, "green"),
        Text(""),
        _bullet_section("Gaps", evaluation.gaps, "yellow"),
        Text(""),
        _bullet_section("Recommendations", evaluation.recommendations, "blue"),
        Text(""),
        Text(evaluation.summary),
    )
    console.print(Panel(content, title=title, border_style=score_style))


def _format_relevant_experience(
    relevant_experience: dict[str, list[Node] | list[Edge]],
) -> str:
    nodes = relevant_experience.get("nodes", [])
    edges = relevant_experience.get("edges", [])
    if not nodes and not edges:
        return "No relevant graph facts were found."

    node_names = {node["id"]: node["name"] for node in nodes}
    lines: list[str] = []
    if nodes:
        lines.append("Nodes:")
        for node in nodes:
            lines.append(
                "- "
                f"{node['id']}: {node['type']} named {node['name']} - "
                f"{node['text_representation']}"
            )
    if edges:
        lines.append("Edges:")
        for edge in edges:
            source = node_names.get(edge["source_id"], edge["source_id"])
            target = node_names.get(edge["target_id"], edge["target_id"])
            lines.append(f"- {source} --{edge['relation']}--> {target}")
    return "\n".join(lines)


def _bullet_section(title: str, items: list[str], style: str) -> Text:
    text = Text(f"{title}\n", style=f"bold {style}")
    if not items:
        text.append("- None identified", style=style)
        return text

    for index, item in enumerate(items):
        if index:
            text.append("\n")
        text.append(f"- {item}", style=style)
    return text


def _score_style(score: float) -> str:
    if score >= 7:
        return "green"
    if score >= 4:
        return "yellow"
    return "red"

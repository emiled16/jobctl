"""Cover letter YAML generation."""

import os
import shlex
import subprocess
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.prompt import Prompt
from rich.syntax import Syntax

from jobctl.generation.schemas import CoverLetterYAML
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


class CoverLetterLLMClient(Protocol):
    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_format: type[CoverLetterYAML],
    ) -> CoverLetterYAML: ...


def generate_cover_letter_yaml(
    jd: ExtractedJD,
    relevant_experience: dict,
    evaluation: FitEvaluation,
    llm_client: CoverLetterLLMClient,
) -> CoverLetterYAML:
    """Generate tailored cover letter YAML from JD and graph context."""
    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise, specific cover letter YAML. Avoid generic claims and "
                "only use evidence from the provided candidate graph."
            ),
        },
        {
            "role": "user",
            "content": (
                "Write a concise cover letter with 3-4 paragraphs.\n\n"
                "Job description:\n"
                f"{yaml.safe_dump(jd.model_dump(), sort_keys=False)}\n"
                "Relevant candidate graph context:\n"
                f"{_format_relevant_experience(relevant_experience)}\n\n"
                "Fit evaluation:\n"
                f"{yaml.safe_dump(evaluation.model_dump(), sort_keys=False)}\n"
                "Instructions:\n"
                "- Open with genuine interest in this specific role and company.\n"
                "- Map 2-3 strongest relevant experiences to top JD requirements.\n"
                "- Address one gap constructively if a gap exists.\n"
                "- Close with a clear call to action."
            ),
        },
    ]
    return llm_client.chat_structured(messages, response_format=CoverLetterYAML)


def save_and_review_cover_letter(
    cover_letter: CoverLetterYAML,
    output_dir: Path,
) -> Path | None:
    """Write cover letter YAML and let the user continue, edit, or regenerate."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cover-letter.yaml"
    _write_cover_letter_yaml(cover_letter, output_path)

    console = Console()
    while True:
        console.print(Syntax(output_path.read_text(encoding="utf-8"), "yaml"))
        choice = Prompt.ask(
            "Review the YAML above. [c]ontinue to PDF / [e]dit in $EDITOR / [r]egenerate",
            choices=["c", "e", "r"],
            default="c",
        ).lower()

        if choice == "c":
            return output_path
        if choice == "r":
            return None

        _open_in_editor(output_path)
        try:
            edited_cover_letter = CoverLetterYAML.model_validate(
                yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
            )
        except (ValidationError, yaml.YAMLError) as exc:
            console.print(f"[red]Invalid cover letter YAML: {exc}[/red]")
            continue
        _write_cover_letter_yaml(edited_cover_letter, output_path)


def _write_cover_letter_yaml(cover_letter: CoverLetterYAML, output_path: Path) -> None:
    output_path.write_text(
        yaml.safe_dump(
            cover_letter.model_dump(mode="json"),
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def _open_in_editor(path: Path) -> None:
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([*shlex.split(editor), str(path)], check=True)


def _format_relevant_experience(relevant_experience: dict) -> str:
    nodes = relevant_experience.get("nodes", [])
    edges = relevant_experience.get("edges", [])
    if not nodes and not edges:
        return "No relevant graph facts were found."

    node_names = {node["id"]: node["name"] for node in nodes}
    lines: list[str] = []
    for node in nodes:
        lines.append(
            f"- {node['id']}: {node['type']} named {node['name']} - {node['text_representation']}"
        )
    for edge in edges:
        source = node_names.get(edge["source_id"], edge["source_id"])
        target = node_names.get(edge["target_id"], edge["target_id"])
        lines.append(f"- {source} --{edge['relation']}--> {target}")
    return "\n".join(lines)

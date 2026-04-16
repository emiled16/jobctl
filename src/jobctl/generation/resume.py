"""Resume YAML generation."""

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

from jobctl.generation.schemas import ResumeYAML
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


class ResumeLLMClient(Protocol):
    def chat_structured(
        self,
        messages: list[dict[str, str]],
        response_format: type[ResumeYAML],
    ) -> ResumeYAML: ...


def generate_resume_yaml(
    jd: ExtractedJD,
    relevant_experience: dict,
    evaluation: FitEvaluation,
    llm_client: ResumeLLMClient,
) -> ResumeYAML:
    """Generate tailored resume YAML from a JD and retrieved profile context."""
    messages = [
        {
            "role": "system",
            "content": (
                "You generate ATS-friendly resume YAML. Use standard section headings, "
                "truthful graph evidence only, concise language, and job-specific keyword alignment."
            ),
        },
        {
            "role": "user",
            "content": (
                "Generate a tailored resume for this job.\n\n"
                "Job description:\n"
                f"{yaml.safe_dump(jd.model_dump(), sort_keys=False)}\n"
                "Relevant candidate graph context:\n"
                f"{_format_relevant_experience(relevant_experience)}\n\n"
                "Fit evaluation:\n"
                f"{yaml.safe_dump(evaluation.model_dump(), sort_keys=False)}\n"
                "ATS instructions:\n"
                "- Use standard resume sections.\n"
                "- Lead bullets with strong action verbs.\n"
                "- Quantify achievements where graph evidence supports it.\n"
                "- Incorporate JD keywords naturally.\n"
                "- Order bullets by relevance to this JD.\n"
                "- Include only skills relevant to the role.\n"
                "- Write a 2-3 sentence summary positioning the candidate for this role.\n"
                "- Keep every bullet specific and evidence-backed."
            ),
        },
    ]
    return llm_client.chat_structured(messages, response_format=ResumeYAML)


def save_and_review(resume: ResumeYAML, output_dir: Path) -> Path | None:
    """Write resume YAML and let the user continue, edit, or regenerate."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "resume.yaml"
    _write_resume_yaml(resume, output_path)

    console = Console()
    while True:
        _print_yaml(console, output_path)
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
            edited_resume = ResumeYAML.model_validate(
                yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
            )
        except (ValidationError, yaml.YAMLError) as exc:
            console.print(f"[red]Invalid resume YAML: {exc}[/red]")
            continue
        _write_resume_yaml(edited_resume, output_path)


def _write_resume_yaml(resume: ResumeYAML, output_path: Path) -> None:
    output_path.write_text(
        yaml.safe_dump(
            resume.model_dump(mode="json"),
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def _print_yaml(console: Console, output_path: Path) -> None:
    console.print(Syntax(output_path.read_text(encoding="utf-8"), "yaml"))


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

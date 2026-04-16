"""End-to-end job application orchestration."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Confirm

from jobctl.config import CONFIG_DIR_NAME, find_project_root
from jobctl.generation.cover_letter import (
    generate_cover_letter_yaml,
    save_and_review_cover_letter,
)
from jobctl.generation.renderer import output_pdf_path, render_pdf
from jobctl.generation.resume import generate_resume_yaml, save_and_review
from jobctl.jobs.evaluator import display_evaluation, evaluate_fit, retrieve_relevant_experience
from jobctl.jobs.fetcher import fetch_and_parse_jd
from jobctl.jobs.tracker import create_application, update_application, update_status


console = Console()


def run_apply(conn: sqlite3.Connection, url_or_text: str, llm_client: Any, config: Any) -> str:
    """Run the full JD evaluation and material generation flow."""
    jd = fetch_and_parse_jd(url_or_text, llm_client)
    relevant_experience = retrieve_relevant_experience(conn, jd, llm_client)
    evaluation = evaluate_fit(jd, relevant_experience, llm_client)
    display_evaluation(jd, evaluation)

    app_id = create_application(
        conn,
        company=jd.company,
        role=jd.title,
        url=url_or_text if url_or_text.startswith(("http://", "https://")) else None,
        jd=jd,
        evaluation=evaluation,
    )

    if not Confirm.ask("Generate tailored materials?", default=True):
        console.print(f"Tracker entry created: {app_id}")
        return app_id

    output_dir = _application_output_dir(jd)
    resume_yaml_path = _generate_reviewed_resume(
        jd, relevant_experience, evaluation, llm_client, output_dir
    )
    resume_pdf_path = render_pdf(resume_yaml_path, "resume.html", output_pdf_path(resume_yaml_path))

    cover_letter_yaml_path: Path | None = None
    cover_letter_pdf_path: Path | None = None
    if Confirm.ask("Generate cover letter?", default=True):
        cover_letter_yaml_path = _generate_reviewed_cover_letter(
            jd,
            relevant_experience,
            evaluation,
            llm_client,
            output_dir,
        )
        cover_letter_pdf_path = render_pdf(
            cover_letter_yaml_path,
            "cover-letter.html",
            output_pdf_path(cover_letter_yaml_path),
        )

    update_application(
        conn,
        app_id,
        resume_yaml_path=str(resume_yaml_path),
        resume_pdf_path=str(resume_pdf_path),
        cover_letter_yaml_path=str(cover_letter_yaml_path) if cover_letter_yaml_path else None,
        cover_letter_pdf_path=str(cover_letter_pdf_path) if cover_letter_pdf_path else None,
    )
    update_status(conn, app_id, "materials_ready")

    console.print(f"Tracker entry created: {app_id}")
    console.print(f"Resume YAML: {resume_yaml_path}")
    console.print(f"Resume PDF: {resume_pdf_path}")
    if cover_letter_yaml_path and cover_letter_pdf_path:
        console.print(f"Cover letter YAML: {cover_letter_yaml_path}")
        console.print(f"Cover letter PDF: {cover_letter_pdf_path}")
    return app_id


def _generate_reviewed_resume(
    jd,
    relevant_experience: dict,
    evaluation,
    llm_client: Any,
    output_dir: Path,
) -> Path:
    while True:
        resume = generate_resume_yaml(jd, relevant_experience, evaluation, llm_client)
        resume_yaml_path = save_and_review(resume, output_dir)
        if resume_yaml_path is not None:
            return resume_yaml_path


def _generate_reviewed_cover_letter(
    jd,
    relevant_experience: dict,
    evaluation,
    llm_client: Any,
    output_dir: Path,
) -> Path:
    while True:
        cover_letter = generate_cover_letter_yaml(jd, relevant_experience, evaluation, llm_client)
        cover_letter_yaml_path = save_and_review_cover_letter(cover_letter, output_dir)
        if cover_letter_yaml_path is not None:
            return cover_letter_yaml_path


def _application_output_dir(jd) -> Path:
    project_root = find_project_root(Path.cwd())
    date_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    company_slug = _slugify(jd.company or "company")
    role_slug = _slugify(jd.title or "role")
    return project_root / CONFIG_DIR_NAME / "exports" / f"{date_prefix}-{company_slug}-{role_slug}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "job"

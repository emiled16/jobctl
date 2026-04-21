from pathlib import Path

from click.testing import CliRunner

from jobctl.cli import main
from jobctl.db.connection import get_connection
from jobctl.db.graph import search_nodes
from jobctl.ingestion.resume import persist_facts
from jobctl.jobs import apply_pipeline
from jobctl.jobs.tracker import get_application
from jobctl.llm.schemas import ExtractedFact, ExtractedJD, FitEvaluation


class FakeLLMClient:
    def get_embedding(self, _text: str) -> list[float]:
        return [0.0] * 1536


def test_init_resume_ingestion_apply_flow(
    tmp_path: Path,
    monkeypatch,
    fake_vector_store,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        project_root = Path(isolated_dir)
        runner.invoke(main, ["init"], catch_exceptions=False)
        conn = get_connection(project_root / ".jobctl" / "jobctl.db")
        try:
            persist_facts(
                conn,
                [
                    ExtractedFact(
                        entity_type="skill",
                        entity_name="Python",
                        relation=None,
                        related_to=None,
                        properties={"years": 8},
                        text_representation="Python engineering",
                    )
                ],
                FakeLLMClient(),
                interactive=False,
                vector_store=fake_vector_store,
            )
            assert search_nodes(conn, type="skill", name_contains="Python")

            monkeypatch.setattr(apply_pipeline, "fetch_and_parse_jd", lambda *_args: make_jd())
            monkeypatch.setattr(
                apply_pipeline,
                "retrieve_relevant_experience",
                lambda *_args: {"nodes": [], "edges": []},
            )
            monkeypatch.setattr(apply_pipeline, "evaluate_fit", lambda *_args: make_eval())
            monkeypatch.setattr(apply_pipeline, "display_evaluation", lambda *_args: None)
            monkeypatch.setattr(apply_pipeline.Confirm, "ask", lambda *_args, **_kwargs: True)
            monkeypatch.setattr(apply_pipeline, "generate_resume_yaml", lambda *_args: object())
            monkeypatch.setattr(
                apply_pipeline,
                "save_and_review",
                lambda _resume, output_dir: write_file(
                    output_dir / "artifacts" / "drafts" / "resume.yaml"
                ),
            )
            monkeypatch.setattr(
                apply_pipeline, "generate_cover_letter_yaml", lambda *_args: object()
            )
            monkeypatch.setattr(
                apply_pipeline,
                "save_and_review_cover_letter",
                lambda _cover, output_dir: write_file(
                    output_dir / "artifacts" / "drafts" / "cover-letter.yaml"
                ),
            )
            monkeypatch.setattr(
                apply_pipeline,
                "render_pdf",
                lambda _yaml_path, _template_name, output_path: write_file(output_path, b"%PDF"),
            )

            app_id = apply_pipeline.run_apply(
                conn,
                "Senior Engineer JD",
                object(),
                object(),
                fake_vector_store,
            )

            application = get_application(conn, app_id)
            assert application["status"] == "materials_ready"
            assert Path(application["resume_pdf_path"]).is_file()
        finally:
            conn.close()


def write_file(path: Path, content: bytes = b"yaml") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build systems"],
        qualifications=[],
        nice_to_haves=[],
        raw_text="Raw JD",
    )


def make_eval() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Python"],
        gaps=[],
        recommendations=["Lead with Python"],
        summary="Strong fit.",
    )

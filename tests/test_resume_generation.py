from pathlib import Path

import pytest
import yaml

from jobctl.generation import resume as resume_generation
from jobctl.generation.schemas import ContactInfo, ResumeYAML
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def chat_structured(self, messages: list[dict[str, str]], response_format: type) -> ResumeYAML:
        self.messages.append(messages)
        assert response_format is ResumeYAML
        return make_resume()


def test_resume_yaml_schema_forbids_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ContactInfo(name="User", email="user@example.com", unknown=True)


def test_generate_resume_yaml_prompts_with_jd_graph_and_evaluation() -> None:
    llm_client = FakeLLMClient()
    relevant_experience = {
        "nodes": [
            {
                "id": "node-1",
                "type": "role",
                "name": "Senior Engineer",
                "text_representation": "Built Python platforms",
            }
        ],
        "edges": [],
    }

    result = resume_generation.generate_resume_yaml(
        make_jd(),
        relevant_experience,
        make_evaluation(),
        llm_client,
    )

    prompt = llm_client.messages[0][1]["content"]
    assert result.contact.email == "user@example.com"
    assert "title: Senior Engineer" in prompt
    assert "node-1: role named Senior Engineer" in prompt
    assert "Built Python platforms" in prompt
    assert "Lead bullets with strong action verbs" in prompt
    assert "No explicit Kubernetes evidence" in prompt


def test_save_and_review_continue_writes_resume_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(resume_generation.Prompt, "ask", lambda *args, **kwargs: "c")

    output_path = resume_generation.save_and_review(make_resume(), tmp_path)

    assert output_path == tmp_path / "artifacts" / "drafts" / "resume.yaml"
    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert data["contact"]["name"] == "Test User"
    assert data["experience"][0]["bullets"] == ["Built Python systems"]
    assert "Test User" in capsys.readouterr().out


def test_save_and_review_regenerate_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resume_generation.Prompt, "ask", lambda *args, **kwargs: "r")

    assert resume_generation.save_and_review(make_resume(), tmp_path) is None


def test_save_and_review_edit_revalidates_written_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = iter(["e", "c"])
    monkeypatch.setattr(resume_generation.Prompt, "ask", lambda *args, **kwargs: next(choices))

    def fake_run(args: list[str], check: bool) -> None:
        assert check is True
        edited_resume = make_resume()
        edited_resume.contact.name = "Edited User"
        Path(args[-1]).write_text(
            yaml.safe_dump(edited_resume.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(resume_generation.subprocess, "run", fake_run)

    output_path = resume_generation.save_and_review(make_resume(), tmp_path)

    assert output_path == tmp_path / "artifacts" / "drafts" / "resume.yaml"
    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert data["contact"]["name"] == "Edited User"


def make_resume() -> ResumeYAML:
    return ResumeYAML(
        contact={
            "name": "Test User",
            "email": "user@example.com",
            "phone": None,
            "location": "Remote",
            "linkedin": None,
            "github": "https://github.com/test",
            "website": None,
        },
        summary="Senior engineer focused on reliable Python systems.",
        experience=[
            {
                "company": "Acme",
                "title": "Senior Engineer",
                "start_date": "2022-01",
                "end_date": None,
                "bullets": ["Built Python systems"],
            }
        ],
        skills={"Languages": ["Python"]},
        education=[
            {
                "institution": "State University",
                "degree": "BS",
                "field": "Computer Science",
                "end_date": "2016",
                "details": None,
            }
        ],
        certifications=None,
        projects=[{"name": "Jobctl", "description": "Career tooling", "url": None}],
    )


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build backend systems"],
        qualifications=["5 years"],
        nice_to_haves=["SQLite"],
        raw_text="Senior Engineer role",
    )


def make_evaluation() -> FitEvaluation:
    return FitEvaluation(
        score=8.0,
        matching_strengths=["Built Python platforms"],
        gaps=["No explicit Kubernetes evidence"],
        recommendations=["Lead with Python platform work"],
        summary="Strong fit with one infrastructure gap.",
    )

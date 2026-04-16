from pathlib import Path

import pytest
import yaml

from jobctl.generation import cover_letter as cover_letter_generation
from jobctl.generation.schemas import CoverLetterYAML
from jobctl.llm.schemas import ExtractedJD, FitEvaluation


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    def chat_structured(
        self, messages: list[dict[str, str]], response_format: type
    ) -> CoverLetterYAML:
        self.messages.append(messages)
        assert response_format is CoverLetterYAML
        return make_cover_letter()


def test_generate_cover_letter_yaml_prompts_with_context() -> None:
    llm_client = FakeLLMClient()

    cover_letter = cover_letter_generation.generate_cover_letter_yaml(
        make_jd(),
        {
            "nodes": [
                {
                    "id": "n1",
                    "type": "role",
                    "name": "Engineer",
                    "text_representation": "Built APIs",
                }
            ]
        },
        make_evaluation(),
        llm_client,
    )

    prompt = llm_client.messages[0][1]["content"]
    assert cover_letter.company == "Acme"
    assert "3-4 paragraphs" in prompt
    assert "Built APIs" in prompt
    assert "No Rails evidence" in prompt


def test_save_and_review_cover_letter_continue_writes_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cover_letter_generation.Prompt, "ask", lambda *args, **kwargs: "c")

    output_path = cover_letter_generation.save_and_review_cover_letter(
        make_cover_letter(), tmp_path
    )

    assert output_path == tmp_path / "cover-letter.yaml"
    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert data["company"] == "Acme"


def test_save_and_review_cover_letter_regenerate_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cover_letter_generation.Prompt, "ask", lambda *args, **kwargs: "r")

    assert (
        cover_letter_generation.save_and_review_cover_letter(make_cover_letter(), tmp_path) is None
    )


def make_cover_letter() -> CoverLetterYAML:
    return CoverLetterYAML(
        recipient=None,
        company="Acme",
        role="Senior Engineer",
        opening="I am interested in the Senior Engineer role.",
        body_paragraphs=["I built APIs."],
        closing="Thank you for your time.",
    )


def make_jd() -> ExtractedJD:
    return ExtractedJD(
        title="Senior Engineer",
        company="Acme",
        location="Remote",
        compensation=None,
        requirements=["Python"],
        responsibilities=["Build APIs"],
        qualifications=["5 years"],
        nice_to_haves=[],
        raw_text="Senior Engineer role",
    )


def make_evaluation() -> FitEvaluation:
    return FitEvaluation(
        score=7.0,
        matching_strengths=["Built APIs"],
        gaps=["No Rails evidence"],
        recommendations=["Lead with API work"],
        summary="Good fit.",
    )

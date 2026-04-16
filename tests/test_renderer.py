from pathlib import Path

import yaml
from click.testing import CliRunner

from jobctl.cli import main
from jobctl.generation import renderer


def test_infer_template_name_and_output_pdf_path() -> None:
    assert renderer.infer_template_name(Path("resume.yaml")) == "resume.html"
    assert renderer.infer_template_name(Path("cover-letter.yaml")) == "cover-letter.html"
    assert renderer.output_pdf_path(Path("resume.yaml")) == Path("resume.pdf")


def test_render_pdf_uses_template_and_writes_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string
            captured["base_url"] = base_url

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    output_path = renderer.render_pdf(yaml_path, "resume.html", tmp_path / "resume.pdf")

    assert output_path.read_bytes() == b"%PDF-test"
    assert "Test User" in captured["html"]


def test_init_copies_bundled_templates(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        result = runner.invoke(main, ["init"], catch_exceptions=False)
        root = Path(isolated_dir)

        assert result.exit_code == 0
        assert (root / ".jobctl" / "templates" / "resume.html").is_file()
        assert (root / ".jobctl" / "templates" / "cover-letter.html").is_file()


def _resume_data() -> dict:
    return {
        "contact": {"name": "Test User", "email": "user@example.com"},
        "summary": "Python engineer.",
        "experience": [],
        "skills": {"Languages": ["Python"]},
        "education": [],
        "certifications": None,
        "projects": None,
    }

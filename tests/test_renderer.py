from pathlib import Path

import yaml
from click.testing import CliRunner

from jobctl.cli import main
from jobctl.generation import renderer


def test_infer_template_name_and_output_pdf_path() -> None:
    assert renderer.infer_template_name(Path("resume.yaml")) == "emile-resume.html"
    assert renderer.infer_template_name(Path("cover-letter.yaml")) == "cover-letter.html"
    assert renderer.output_pdf_path(Path("resume.yaml")) == Path("resume.pdf")
    assert renderer.output_pdf_path(Path("export/artifacts/drafts/resume.yaml")) == Path(
        "export/artifacts/final/resume.pdf"
    )


def test_list_template_names_includes_resume_templates() -> None:
    templates = renderer.list_template_names(Path("resume.yaml"))

    assert "resume.html" in templates
    assert "compact-resume.html" in templates
    assert "emile-resume.html" in templates
    assert "modern-resume.html" in templates
    assert "cover-letter.html" not in templates


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


def test_render_pdf_respects_disabled_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["projects"] = [{"name": "Hidden Project", "description": "Should not render"}]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    renderer.render_pdf(
        yaml_path,
        "resume.html",
        tmp_path / "resume.pdf",
        disable_sections={"projects"},
    )

    assert "Hidden Project" not in captured["html"]
    assert "Projects" not in captured["html"]


def test_render_pdf_uses_declared_section_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["render"] = {
        "sections": {
            "projects": {"enabled": True, "title": "Selected Work", "order": 15},
            "education": {"enabled": False},
        }
    }
    data["projects"] = [{"name": "Jobctl", "description": "Career tooling"}]
    data["education"] = [{"institution": "State", "degree": "BS"}]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    renderer.render_pdf(yaml_path, "resume.html", tmp_path / "resume.pdf")

    assert "Selected Work" in captured["html"]
    assert "Jobctl" in captured["html"]
    assert "Education" not in captured["html"]


def test_render_pdf_uses_manual_section_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["experience"] = [
        {
            "company": "Acme",
            "title": "Engineer",
            "start_date": "2024-01",
            "end_date": None,
            "bullets": ["Built renderers"],
        }
    ]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    renderer.render_pdf(
        yaml_path,
        "resume.html",
        tmp_path / "resume.pdf",
        section_order=["skills", "summary", "experience", "education"],
    )

    assert captured["html"].index("Skills") < captured["html"].index("Summary")


def test_emile_template_renders_clickable_social_links(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["contact"]["linkedin"] = "https://linkedin.com/in/test-user"
    data["contact"]["github"] = "https://github.com/test-user"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    renderer.render_pdf(yaml_path, "emile-resume.html", tmp_path / "resume.pdf")

    assert 'href="https://linkedin.com/in/test-user"' in captured["html"]
    assert 'aria-label="LinkedIn profile"' in captured["html"]
    assert 'href="https://github.com/test-user"' in captured["html"]
    assert 'aria-label="GitHub profile"' in captured["html"]


def test_document_type_overrides_filename_for_template_inference(tmp_path: Path) -> None:
    yaml_path = tmp_path / "letter.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"document_type": "resume", **_resume_data()}, sort_keys=False),
        encoding="utf-8",
    )

    loaded = renderer.load_material(yaml_path)

    assert loaded.document_type == "resume"
    assert renderer.infer_template_name(yaml_path, loaded) == "emile-resume.html"


def test_invalid_resume_yaml_suggests_close_field_name(tmp_path: Path) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["skilss"] = data.pop("skills")
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    try:
        renderer.load_material(yaml_path)
    except renderer.MaterialValidationError as exc:
        assert "Did you mean `skills`" in str(exc)
    else:
        raise AssertionError("Expected MaterialValidationError")


def test_render_cli_can_disable_section(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["projects"] = [{"name": "Hidden Project", "description": "Should not render"}]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    result = runner.invoke(
        main,
        ["render", "--disable", "projects", str(yaml_path)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "Hidden Project" not in captured["html"]


def test_render_cli_validate_only_does_not_write_pdf(tmp_path: Path) -> None:
    runner = CliRunner()
    yaml_path = tmp_path / "resume.yaml"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")

    result = runner.invoke(main, ["render", "--validate-only", str(yaml_path)])

    assert result.exit_code == 0
    assert "valid" in result.output
    assert not (tmp_path / "resume.pdf").exists()


def test_init_copies_bundled_templates(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        result = runner.invoke(main, ["init"], catch_exceptions=False)
        root = Path(isolated_dir)

        assert result.exit_code == 0
        assert (root / ".jobctl" / "templates" / "resume" / "resume.html").is_file()
        assert (root / ".jobctl" / "templates" / "resume" / "compact-resume.html").is_file()
        assert (root / ".jobctl" / "templates" / "resume" / "emile-resume.html").is_file()
        assert (root / ".jobctl" / "templates" / "resume" / "modern-resume.html").is_file()
        assert (
            root / ".jobctl" / "templates" / "cover-letters" / "cover-letter.html"
        ).is_file()


def _resume_data() -> dict:
    return {
        "contact": {"name": "Test User", "email": "user@example.com"},
        "summary": "Python engineer.",
        "experience": [],
        "skills": {"Languages": ["Python"]},
        "education": [],
        "certifications": None,
        "projects": None,
        "publications": None,
    }

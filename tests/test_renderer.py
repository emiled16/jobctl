from pathlib import Path

import yaml
from click.testing import CliRunner

from jobctl.cli import main
from jobctl.generation import renderer
from jobctl.tui import materials_render


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


def test_render_cli_interactive_opens_tui(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    yaml_path = tmp_path / "resume.yaml"
    output_path = tmp_path / "selected.pdf"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")
    captured: dict[str, Path | None] = {}

    def fake_run_material_render_tui(
        path: Path,
        *,
        template_name: str | None = None,
        output_path: Path | None = None,
    ) -> materials_render.MaterialRenderResult:
        captured["path"] = path
        captured["template_name"] = Path(template_name) if template_name else None
        captured["output_path"] = output_path
        return materials_render.MaterialRenderResult(output_path=output_path, rendered=True)

    monkeypatch.setattr(
        materials_render,
        "run_material_render_tui",
        fake_run_material_render_tui,
    )

    result = runner.invoke(
        main,
        ["render", "--interactive", "--output", str(output_path), str(yaml_path)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert captured["path"] == yaml_path
    assert captured["output_path"] == output_path
    assert str(output_path) in result.output


def test_material_render_app_renders_pdf_headlessly(tmp_path: Path, monkeypatch) -> None:
    yaml_path = tmp_path / "resume.yaml"
    data = _resume_data()
    data["projects"] = [{"name": "Hidden Project", "description": "Should not render"}]
    data["render"] = {"sections": {"projects": {"enabled": False}}}
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    output_path = tmp_path / "resume.pdf"
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=output_path)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.pause(0.1)
            assert app.return_value is None
            assert app.last_printed_path == output_path

    import asyncio

    asyncio.run(run_app())

    assert output_path.read_bytes() == b"%PDF-test"
    assert "Hidden Project" not in captured["html"]


def test_material_render_app_supports_keyboard_section_toggle(
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
            "bullets": ["Built readable TUIs"],
        }
    ]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    output_path = tmp_path / "resume.pdf"
    captured: dict[str, str] = {}

    class FakeHTML:
        def __init__(self, string: str, base_url: str) -> None:
            captured["html"] = string

        def write_pdf(self, output_path: Path) -> None:
            Path(output_path).write_bytes(b"%PDF-test")

    monkeypatch.setattr(renderer, "_html_class", lambda: FakeHTML)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=output_path)
        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("p")
            await pilot.pause(0.1)

    import asyncio

    asyncio.run(run_app())

    assert "Acme" not in captured["html"]


def test_material_render_app_supports_manual_section_sorting(
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
    output_path = tmp_path / "resume.pdf"
    captured: dict[str, list[str]] = {}

    def fake_render_pdf(
        yaml_path: Path,
        template_name: str | None,
        output_path: Path,
        **kwargs,
    ) -> Path:
        captured["section_order"] = list(kwargs["section_order"])
        output_path.write_bytes(b"%PDF-test")
        return output_path

    monkeypatch.setattr(materials_render, "render_pdf", fake_render_pdf)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=output_path)
        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.press("u")
            await pilot.press("p")
            await pilot.pause(0.1)

    import asyncio

    asyncio.run(run_app())

    assert captured["section_order"][:2] == ["experience", "summary"]


def test_material_render_app_supports_template_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")
    output_path = tmp_path / "resume.pdf"
    captured: dict[str, str | Path] = {}

    def fake_render_pdf(
        yaml_path: Path,
        template_name: str | None,
        output_path: Path,
        **kwargs,
    ) -> Path:
        captured["template_name"] = template_name or ""
        captured["output_path"] = output_path
        output_path.write_bytes(b"%PDF-test")
        return output_path

    monkeypatch.setattr(materials_render, "render_pdf", fake_render_pdf)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=output_path)
        async with app.run_test() as pilot:
            await pilot.press("t")
            await pilot.press("enter")
            await pilot.press("p")
            await pilot.pause(0.1)

    import asyncio

    asyncio.run(run_app())

    assert captured["template_name"] == "compact-resume.html"
    assert captured["output_path"] == output_path


def test_material_render_app_supports_output_filename_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")
    initial_output_path = tmp_path / "initial.pdf"
    edited_output_path = tmp_path / "edited.pdf"
    captured: dict[str, Path] = {}

    def fake_render_pdf(
        yaml_path: Path,
        template_name: str | None,
        output_path: Path,
        **kwargs,
    ) -> Path:
        captured["output_path"] = output_path
        output_path.write_bytes(b"%PDF-test")
        return output_path

    monkeypatch.setattr(materials_render, "render_pdf", fake_render_pdf)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=initial_output_path)
        async with app.run_test() as pilot:
            await pilot.press("o")
            app.query_one("#output-path", materials_render.Input).value = str(edited_output_path)
            await pilot.press("enter")
            await pilot.pause(0.1)

    import asyncio

    asyncio.run(run_app())

    assert captured["output_path"] == edited_output_path
    assert edited_output_path.read_bytes() == b"%PDF-test"


def test_material_render_app_shows_weasyprint_runtime_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yaml_path = tmp_path / "resume.yaml"
    yaml_path.write_text(yaml.safe_dump(_resume_data(), sort_keys=False), encoding="utf-8")
    output_path = tmp_path / "resume.pdf"
    error_message = (
        "WeasyPrint system libraries are missing. Install WeasyPrint native "
        "dependencies, then rerun `jobctl render`."
    )

    def fake_render_pdf(*args, **kwargs) -> Path:
        raise RuntimeError(error_message)

    monkeypatch.setattr(materials_render, "render_pdf", fake_render_pdf)

    async def run_app() -> None:
        app = materials_render.MaterialRenderApp(yaml_path, output_path=output_path)
        async with app.run_test() as pilot:
            await pilot.press("p")
            await pilot.pause(0.1)
            detail = app.query_one("#details", materials_render.Static).renderable
            assert "Print error" in str(detail)
            assert error_message in str(detail)

    import asyncio

    asyncio.run(run_app())

    assert not output_path.exists()


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

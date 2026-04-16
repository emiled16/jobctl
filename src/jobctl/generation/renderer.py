"""YAML to HTML and PDF rendering."""

from importlib import resources
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from jobctl.config import CONFIG_DIR_NAME, find_project_root
from jobctl.generation.schemas import CoverLetterYAML, ResumeYAML


def render_pdf(yaml_path: Path, template_name: str, output_path: Path) -> Path:
    """Render a generated YAML document to PDF."""
    yaml_path = yaml_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model = _load_material(yaml_path)
    template = _load_template(yaml_path, template_name)
    html = template.render(**model.model_dump(mode="json"))
    _html_class()(string=html, base_url=str(yaml_path.parent)).write_pdf(output_path)
    return output_path


def infer_template_name(yaml_path: Path) -> str:
    name = yaml_path.name.lower()
    if "cover" in name:
        return "cover-letter.html"
    return "resume.html"


def output_pdf_path(yaml_path: Path) -> Path:
    stem = yaml_path.stem
    return yaml_path.with_name(f"{stem}.pdf")


def _load_material(yaml_path: Path) -> ResumeYAML | CoverLetterYAML:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if "cover" in yaml_path.name.lower():
        return CoverLetterYAML.model_validate(data)
    return ResumeYAML.model_validate(data)


def _load_template(yaml_path: Path, template_name: str):
    search_paths = []
    try:
        project_root = find_project_root(yaml_path.parent)
        search_paths.append(str(project_root / CONFIG_DIR_NAME / "templates"))
    except Exception:
        pass

    bundled_templates = resources.files("jobctl").joinpath("templates")
    search_paths.append(str(bundled_templates))
    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=select_autoescape(("html", "xml")),
    )
    return env.get_template(template_name)


def _html_class():
    try:
        from weasyprint import HTML
    except OSError as exc:
        raise RuntimeError(
            "WeasyPrint system libraries are missing. Install WeasyPrint native "
            "dependencies, then rerun `jobctl render`."
        ) from exc
    return HTML

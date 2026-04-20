"""YAML to HTML and PDF rendering."""

from collections.abc import Iterable
from dataclasses import dataclass
from difflib import get_close_matches
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from jobctl.config import CONFIG_DIR_NAME, find_project_root
from jobctl.generation.schemas import CoverLetterYAML, ResumeYAML


RESUME_SECTION_DEFAULTS = {
    "summary": ("Summary", 10),
    "experience": ("Experience", 20),
    "skills": ("Skills", 30),
    "education": ("Education", 40),
    "certifications": ("Certifications", 50),
    "projects": ("Projects", 60),
    "publications": ("Publications", 70),
}

TEMPLATE_DIRS = {
    "resume": "resume",
    "cover_letter": "cover-letters",
}


class MaterialValidationError(ValueError):
    """Raised when material YAML cannot be loaded into a supported schema."""


@dataclass(frozen=True)
class LoadedMaterial:
    document_type: str
    model: ResumeYAML | CoverLetterYAML


def render_pdf(
    yaml_path: Path,
    template_name: str | None,
    output_path: Path,
    *,
    enable_sections: Iterable[str] = (),
    disable_sections: Iterable[str] = (),
    section_order: Iterable[str] = (),
) -> Path:
    """Render a generated YAML document to PDF."""
    yaml_path = yaml_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    loaded = load_material(yaml_path)
    selected_template = template_name or infer_template_name(yaml_path, loaded)
    template = _load_template(yaml_path, selected_template)
    context = build_template_context(
        loaded,
        enable_sections=enable_sections,
        disable_sections=disable_sections,
        section_order=section_order,
    )
    html = template.render(**context)
    _html_class()(string=html, base_url=str(yaml_path.parent)).write_pdf(output_path)
    return output_path


def infer_template_name(yaml_path: Path, loaded: LoadedMaterial | None = None) -> str:
    if loaded and loaded.document_type == "cover_letter":
        return "cover-letter.html"
    if loaded and isinstance(loaded.model, ResumeYAML) and loaded.model.render:
        if loaded.model.render.template:
            return loaded.model.render.template
    name = yaml_path.name.lower()
    if "cover" in name:
        return "cover-letter.html"
    return "emile-resume.html"


def output_pdf_path(yaml_path: Path) -> Path:
    stem = yaml_path.stem
    if yaml_path.parent.name == "drafts" and yaml_path.parent.parent.name == "artifacts":
        return yaml_path.parent.parent / "final" / f"{stem}.pdf"
    return yaml_path.with_name(f"{stem}.pdf")


def list_template_names(yaml_path: Path, document_type: str = "resume") -> list[str]:
    """List available template names for the material type."""
    templates: set[str] = set()
    for template_dir in _template_search_paths(yaml_path, document_type=document_type):
        path = Path(template_dir)
        if not path.exists():
            continue
        templates.update(
            child.name for child in path.glob("*.html") if _matches_type(child.name, document_type)
        )
    return sorted(templates)


def validate_material(
    yaml_path: Path,
    *,
    enable_sections: Iterable[str] = (),
    disable_sections: Iterable[str] = (),
    section_order: Iterable[str] = (),
) -> list[str]:
    """Return non-fatal diagnostics for a material YAML file."""
    loaded = load_material(yaml_path)
    if loaded.document_type != "resume":
        return []

    resume = loaded.model
    enabled_overrides = set(enable_sections)
    disabled_overrides = set(disable_sections)
    sections_config = resume.render.sections if resume.render else {}
    base_context = resume.model_dump(mode="json")
    diagnostics: list[str] = []
    for section_name in RESUME_SECTION_DEFAULTS:
        config = sections_config.get(section_name)
        enabled = config.enabled if config else True
        if section_name in enabled_overrides:
            enabled = True
        if section_name in disabled_overrides:
            enabled = False
        explicitly_enabled = section_name in enabled_overrides or (
            config is not None and config.enabled
        )
        if (
            enabled
            and explicitly_enabled
            and not _has_section_content(base_context.get(section_name))
        ):
            diagnostics.append(f"Section `{section_name}` is enabled but has no content.")
    return diagnostics


def load_material(yaml_path: Path) -> LoadedMaterial:
    """Load material YAML and validate it against the matching schema."""
    data = _read_yaml_mapping(yaml_path)
    document_type = _document_type(data, yaml_path)
    try:
        if document_type == "cover_letter":
            return LoadedMaterial(document_type, CoverLetterYAML.model_validate(data))
        return LoadedMaterial(document_type, ResumeYAML.model_validate(data))
    except ValidationError as exc:
        raise MaterialValidationError(_format_validation_error(exc, data)) from exc


def build_template_context(
    loaded: LoadedMaterial,
    *,
    enable_sections: Iterable[str] = (),
    disable_sections: Iterable[str] = (),
    section_order: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the Jinja context for the loaded material."""
    if loaded.document_type == "resume":
        return build_resume_context(
            loaded.model,
            enable_sections=enable_sections,
            disable_sections=disable_sections,
            section_order=section_order,
        )
    return loaded.model.model_dump(mode="json")


def build_resume_context(
    resume: ResumeYAML,
    *,
    enable_sections: Iterable[str] = (),
    disable_sections: Iterable[str] = (),
    section_order: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a resume template context with resolved section visibility."""
    enabled_overrides = set(enable_sections)
    disabled_overrides = set(disable_sections)
    sections_config = resume.render.sections if resume.render else {}
    sections = []
    base_context = resume.model_dump(mode="json")

    manual_order = {name: index for index, name in enumerate(section_order)}

    for name, (default_title, default_order) in RESUME_SECTION_DEFAULTS.items():
        config = sections_config.get(name)
        content = base_context.get(name)
        enabled = config.enabled if config else True
        if name in enabled_overrides:
            enabled = True
        if name in disabled_overrides:
            enabled = False
        has_content = _has_section_content(content)
        if enabled and has_content:
            sections.append(
                {
                    "name": name,
                    "title": config.title if config and config.title else default_title,
                    "order": _section_order_value(
                        name,
                        manual_order,
                        config.order if config else None,
                        default_order,
                    ),
                    "content": content,
                    "kind": name,
                    "enabled": enabled,
                    "has_content": has_content,
                }
            )

    context = {**base_context, "sections": sorted(sections, key=lambda section: section["order"])}
    return context


def _section_order_value(
    section_name: str,
    manual_order: dict[str, int],
    configured_order: int | None,
    default_order: int,
) -> int:
    if section_name in manual_order:
        return manual_order[section_name]
    if manual_order:
        return len(manual_order) + default_order
    if configured_order is not None:
        return configured_order
    return default_order


def _read_yaml_mapping(yaml_path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise MaterialValidationError(f"Invalid YAML in {yaml_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MaterialValidationError(f"Expected {yaml_path} to contain a YAML mapping.")
    return data


def _document_type(data: dict[str, Any], yaml_path: Path) -> str:
    declared = data.get("document_type")
    if declared in {"cover_letter", "cover-letter"}:
        return "cover_letter"
    if declared == "resume":
        return "resume"
    if "cover" in yaml_path.name.lower():
        return "cover_letter"
    return "resume"


def _has_section_content(content: Any) -> bool:
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, dict | list | tuple | set):
        return bool(content)
    return True


def _format_validation_error(exc: ValidationError, data: dict[str, Any]) -> str:
    messages = []
    valid_fields = set(ResumeYAML.model_fields) | set(CoverLetterYAML.model_fields)
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        message = f"{location}: {error['msg']}"
        if error["type"] == "extra_forbidden" and location in data:
            suggestion = get_close_matches(location, valid_fields, n=1)
            if suggestion:
                message = f"{message}. Did you mean `{suggestion[0]}`?"
        messages.append(message)
    return "Invalid material YAML:\n" + "\n".join(f"- {message}" for message in messages)


def _load_template(yaml_path: Path, template_name: str):
    search_paths = _template_search_paths(yaml_path)
    env = Environment(
        loader=FileSystemLoader(search_paths),
        autoescape=select_autoescape(("html", "xml")),
    )
    return env.get_template(template_name)


def _template_search_paths(yaml_path: Path, document_type: str | None = None) -> list[str]:
    if document_type is None:
        data = _read_yaml_mapping(yaml_path) if yaml_path.exists() else {}
        document_type = _document_type(data, yaml_path)
    template_subdir = TEMPLATE_DIRS[document_type]
    search_paths = []
    try:
        project_root = find_project_root(yaml_path.parent)
        project_templates = project_root / CONFIG_DIR_NAME / "templates"
        search_paths.append(str(project_templates / template_subdir))
        search_paths.append(str(project_templates))
    except Exception:
        pass

    bundled_templates = resources.files("jobctl").joinpath("templates")
    search_paths.append(str(bundled_templates.joinpath(template_subdir)))
    search_paths.append(str(bundled_templates))
    return search_paths


def _matches_type(template_name: str, document_type: str) -> bool:
    normalized = template_name.lower()
    if document_type == "cover_letter":
        return "cover" in normalized
    return "cover" not in normalized


def _html_class():
    try:
        from weasyprint import HTML
    except OSError as exc:
        raise RuntimeError(
            "WeasyPrint system libraries are missing. Install WeasyPrint native "
            "dependencies, then rerun `jobctl render`."
        ) from exc
    return HTML

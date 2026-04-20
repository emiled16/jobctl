"""Headless material rendering command (retained after v2 deprecation sweep)."""

from pathlib import Path
from typing import Annotated

import typer

from jobctl.app.common import command_error, validate_section_names

app = typer.Typer(
    help="Render generated YAML materials to PDFs (headless only).",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def render(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(exists=True, readable=True, help="YAML file or folder."),
    ],
    enable_sections: Annotated[
        list[str],
        typer.Option("--enable", help="Resume section to include."),
    ] = [],
    disable_sections: Annotated[
        list[str],
        typer.Option("--disable", help="Resume section to omit."),
    ] = [],
    template_name: Annotated[
        str | None,
        typer.Option("--template", help="Template filename to use."),
    ] = None,
    output_path: Annotated[
        Path | None,
        typer.Option("--output", help="Output PDF path."),
    ] = None,
    validate_only: Annotated[
        bool,
        typer.Option("--validate-only", help="Validate YAML without rendering a PDF."),
    ] = False,
    headless: Annotated[
        bool,
        typer.Option(
            "--headless/--no-headless",
            help=(
                "Retained for backward compatibility; --no-headless now "
                "redirects to the unified TUI."
            ),
        ),
    ] = True,
) -> None:
    """Render generated YAML materials to PDFs without launching the TUI."""
    if ctx.invoked_subcommand is not None:
        return

    if not headless:
        typer.echo(
            "Interactive render is only available via `jobctl` (Apply view).",
            err=True,
        )
        from jobctl.app.common import run_tui

        run_tui("apply")
        return

    try:
        from jobctl.generation.renderer import (
            RESUME_SECTION_DEFAULTS,
            load_material,
            output_pdf_path,
            render_pdf,
            validate_material,
        )

        yaml_paths = sorted(path.rglob("*.yaml")) if path.is_dir() else [path]
        if not yaml_paths:
            raise command_error(f"No YAML files found in {path}")
        if output_path is not None and len(yaml_paths) > 1:
            raise command_error("--output can only be used with a single YAML file.")

        validate_section_names(enable_sections, RESUME_SECTION_DEFAULTS)
        validate_section_names(disable_sections, RESUME_SECTION_DEFAULTS)

        for yaml_path in yaml_paths:
            enabled = set(enable_sections)
            disabled = set(disable_sections)
            load_material(yaml_path)

            diagnostics = validate_material(
                yaml_path,
                enable_sections=enabled,
                disable_sections=disabled,
            )
            if diagnostics:
                for diagnostic in diagnostics:
                    typer.echo(f"Warning: {diagnostic}", err=True)
            if validate_only:
                if not diagnostics:
                    typer.echo(f"{yaml_path}: valid")
                continue

            pdf_path = render_pdf(
                yaml_path,
                template_name,
                output_path or output_pdf_path(yaml_path),
                enable_sections=enabled,
                disable_sections=disabled,
            )
            typer.echo(str(pdf_path))
    except Exception as exc:
        raise command_error(f"Failed to render PDF: {exc}") from exc

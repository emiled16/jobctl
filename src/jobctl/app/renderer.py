"""Material rendering command."""

from pathlib import Path
from typing import Annotated

import typer

from jobctl.app.common import command_error, validate_section_names

app = typer.Typer(help="Render generated YAML materials.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def render(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(exists=True, readable=True, help="YAML file or folder.")],
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
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Open the resume section picker TUI."),
    ] = False,
    use_tui: Annotated[
        bool,
        typer.Option("--tui", help="Open the resume section picker TUI."),
    ] = False,
) -> None:
    """Render generated YAML materials to output files."""
    if ctx.invoked_subcommand is not None:
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
        if (interactive or use_tui) and len(yaml_paths) > 1:
            raise command_error("The render TUI can only be used with a single YAML file.")

        validate_section_names(enable_sections, RESUME_SECTION_DEFAULTS)
        validate_section_names(disable_sections, RESUME_SECTION_DEFAULTS)

        if interactive or use_tui:
            from jobctl.tui.materials_render import run_material_render_tui

            result = run_material_render_tui(
                yaml_paths[0],
                template_name=template_name,
                output_path=output_path,
            )
            if result and result.rendered and result.output_path:
                typer.echo(str(result.output_path))
            return

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

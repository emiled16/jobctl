"""Click command-line interface for jobctl."""

from dataclasses import asdict
from importlib import resources
import logging
from pathlib import Path
import shutil
import sqlite3

import click

from jobctl.config import (
    CONFIG_DIR_NAME,
    ConfigError,
    JobctlConfig,
    config_field_names,
    default_config,
    find_project_root,
    load_config,
    replace_config_value,
    save_config,
)


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.option("--quiet", is_flag=True, help="Suppress non-essential output.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """AI-powered job search assistant."""
    if verbose and quiet:
        raise click.UsageError("Use either --verbose or --quiet, not both.")
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    ctx.obj = {"quiet": quiet, "verbose": verbose}


@main.command("init")
def init_command() -> None:
    """Initialize a jobctl project in the current directory."""
    project_root = Path.cwd()
    jobctl_dir = project_root / CONFIG_DIR_NAME

    if jobctl_dir.exists():
        raise click.ClickException(f"{CONFIG_DIR_NAME}/ already exists in {project_root}")

    (jobctl_dir / "templates").mkdir(parents=True)
    (jobctl_dir / "exports").mkdir()
    _copy_bundled_templates(jobctl_dir / "templates")
    save_config(project_root, default_config())

    click.echo("Initialized .jobctl/. Next, run `jobctl config openai_api_key <key>`.")


@main.command()
def onboard() -> None:
    """Start the onboarding conversation."""
    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.conversation.onboard import run_onboarding
        from jobctl.db.connection import get_connection
        from jobctl.llm.client import LLMClient

        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        llm_client = LLMClient(
            api_key=config.openai_api_key,
            model=config.llm_model,
            cwd=project_root,
        )
        conn = get_connection(db_path)
        try:
            run_onboarding(conn, llm_client, config)
        finally:
            conn.close()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
def yap() -> None:
    """Add profile knowledge from freeform notes."""
    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.conversation.yap import run_yap
        from jobctl.db.connection import get_connection
        from jobctl.llm.client import LLMClient

        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        llm_client = LLMClient(
            api_key=config.openai_api_key, model=config.llm_model, cwd=project_root
        )
        conn = get_connection(db_path)
        try:
            run_yap(conn, llm_client)
        finally:
            conn.close()
    except KeyboardInterrupt:
        click.echo("\nYap session interrupted. Progress has been saved.")
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("url", required=False)
def apply(url: str | None) -> None:
    """Evaluate and tailor materials for a job URL."""
    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from rich.prompt import Prompt

        from jobctl.db.connection import get_connection
        from jobctl.jobs.apply_pipeline import run_apply
        from jobctl.llm.client import LLMClient

        url_or_text = url or Prompt.ask("Job URL or pasted JD")
        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        llm_client = LLMClient(
            api_key=config.openai_api_key,
            model=config.llm_model,
            cwd=project_root,
        )
        conn = get_connection(db_path)
        try:
            run_apply(conn, url_or_text, llm_client, config)
        finally:
            conn.close()
    except KeyboardInterrupt:
        click.echo("\nApply interrupted. Any completed tracker updates have been saved.")
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    except sqlite3.Error as exc:
        raise click.ClickException(
            f"SQLite error. Run `jobctl init` first if needed. {exc}"
        ) from exc


@main.command()
def track() -> None:
    """Open or update the application tracker."""
    _run_tui(start_screen="tracker")


@main.command()
def profile() -> None:
    """Inspect the stored career profile."""
    _run_tui(start_screen="profile")


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def render(path: Path) -> None:
    """Render generated YAML materials to output files."""
    try:
        from jobctl.generation.renderer import infer_template_name, output_pdf_path, render_pdf

        yaml_paths = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
        if not yaml_paths:
            raise click.ClickException(f"No YAML files found in {path}")
        for yaml_path in yaml_paths:
            template_name = infer_template_name(yaml_path)
            pdf_path = render_pdf(yaml_path, template_name, output_pdf_path(yaml_path))
            click.echo(str(pdf_path))
    except Exception as exc:
        raise click.ClickException(f"Failed to render PDF: {exc}") from exc


@main.command("config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_command(key: str | None, value: str | None) -> None:
    """View or update project configuration."""
    if (key is None) != (value is None):
        raise click.UsageError("Provide both KEY and VALUE, or neither.")

    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        if key is None:
            _print_config(config)
            return

        updated_config = replace_config_value(config, key, value or "")
        save_config(project_root, updated_config)
        click.echo(f"Updated {key}.")
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


def _print_config(config: JobctlConfig) -> None:
    values = asdict(config)
    values["openai_api_key"] = _mask_api_key(config.openai_api_key)

    try:
        from rich.console import Console
        from rich.table import Table
    except ModuleNotFoundError:
        for field in config_field_names():
            click.echo(f"{field}: {values[field]}")
        return

    table = Table(title="jobctl config")
    table.add_column("Key")
    table.add_column("Value")
    for field in config_field_names():
        table.add_row(field, values[field])

    Console().print(table)


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * (len(api_key) - 4)}{api_key[-4:]}"


def _copy_bundled_templates(destination: Path) -> None:
    template_root = resources.files("jobctl").joinpath("templates")
    for template_name in ("resume.html", "cover-letter.html"):
        source = template_root.joinpath(template_name)
        with resources.as_file(source) as source_path:
            shutil.copyfile(source_path, destination / template_name)


def _run_tui(start_screen: str) -> None:
    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.db.connection import get_connection
        from jobctl.llm.client import LLMClient
        from jobctl.tui.app import JobctlApp

        llm_client = LLMClient(
            api_key=config.openai_api_key,
            model=config.llm_model,
            cwd=project_root,
        )
        conn = get_connection(project_root / CONFIG_DIR_NAME / "jobctl.db")
        try:
            JobctlApp(
                conn=conn,
                project_root=project_root,
                start_screen=start_screen,
                llm_client=llm_client,
            ).run()
        finally:
            conn.close()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

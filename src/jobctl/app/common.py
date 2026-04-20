"""Shared helpers for Typer command modules."""

from importlib import resources
from pathlib import Path
import shutil

import click
import typer

from jobctl.config import (
    CONFIG_DIR_NAME,
    ConfigError,
    JobctlConfig,
    config_field_names,
    find_project_root,
    load_config,
)


def command_error(message: str) -> click.ClickException:
    """Return a Click-compatible error for Typer commands."""
    return click.ClickException(message)


def validate_section_names(
    section_names: tuple[str, ...] | list[str],
    known_sections: dict[str, tuple[str, int]],
) -> None:
    unknown = sorted(set(section_names) - set(known_sections))
    if unknown:
        valid = ", ".join(known_sections)
        raise command_error(
            f"Unknown resume section(s): {', '.join(unknown)}. Valid sections: {valid}"
        )


def print_config(config: JobctlConfig) -> None:
    values: dict[str, str] = {
        "llm.provider": config.llm.provider,
        "llm.chat_model": config.llm.chat_model,
        "llm.embedding_model": config.llm.embedding_model,
        "llm.openai.api_key_env": config.llm.openai.api_key_env,
        "llm.ollama.host": config.llm.ollama.host,
        "llm.ollama.embedding_model": config.llm.ollama.embedding_model,
        "default_template": config.default_template,
    }

    try:
        from rich.console import Console
        from rich.table import Table
    except ModuleNotFoundError:
        for key in config_field_names():
            typer.echo(f"{key}: {values[key]}")
        return

    table = Table(title="jobctl config")
    table.add_column("Key")
    table.add_column("Value")
    for key in config_field_names():
        table.add_row(key, values[key])

    Console().print(table)


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "*" * len(api_key)
    return f"{'*' * (len(api_key) - 4)}{api_key[-4:]}"


def copy_bundled_templates(destination: Path) -> None:
    template_root = resources.files("jobctl").joinpath("templates")
    for source in template_root.iterdir():
        if not source.is_dir():
            continue
        target_dir = destination / source.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for template in source.iterdir():
            if template.name.endswith(".html"):
                with resources.as_file(template) as source_path:
                    shutil.copyfile(source_path, target_dir / template.name)


def run_tui(start_screen: str = "chat", initial_message: str | None = None) -> None:
    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.db.connection import get_connection
        from jobctl.llm.registry import get_provider
        from jobctl.tui.app import JobctlApp

        provider = get_provider(config, cwd=project_root)
        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        conn = get_connection(db_path)
        try:
            JobctlApp(
                conn=conn,
                project_root=project_root,
                config=config,
                provider=provider,
                db_path=db_path,
                start_screen=start_screen,
                initial_message=initial_message,
            ).run()
        finally:
            conn.close()
    except ConfigError as exc:
        raise command_error(str(exc)) from exc


def deprecation_warning(command: str, replacement: str) -> None:
    """Print a deprecation warning for a legacy subcommand."""
    typer.echo(
        f"`jobctl {command}` is deprecated and will be removed in a future "
        f"release. Use `{replacement}` instead.",
        err=True,
    )

"""Click command-line interface for jobctl."""

from dataclasses import asdict
from pathlib import Path

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
def main() -> None:
    """AI-powered job search assistant."""


@main.command("init")
def init_command() -> None:
    """Initialize a jobctl project in the current directory."""
    project_root = Path.cwd()
    jobctl_dir = project_root / CONFIG_DIR_NAME

    if jobctl_dir.exists():
        raise click.ClickException(f"{CONFIG_DIR_NAME}/ already exists in {project_root}")

    (jobctl_dir / "templates").mkdir(parents=True)
    (jobctl_dir / "exports").mkdir()
    save_config(project_root, default_config())

    click.echo("Initialized .jobctl/. Next, run `jobctl config openai_api_key <key>`.")


@main.command()
def onboard() -> None:
    """Start the onboarding conversation."""
    click.echo("not implemented yet")


@main.command()
def yap() -> None:
    """Add profile knowledge from freeform notes."""
    click.echo("not implemented yet")


@main.command()
def apply() -> None:
    """Evaluate and tailor materials for a job URL."""
    click.echo("not implemented yet")


@main.command()
def track() -> None:
    """Open or update the application tracker."""
    click.echo("not implemented yet")


@main.command()
def profile() -> None:
    """Inspect the stored career profile."""
    click.echo("not implemented yet")


@main.command()
def render() -> None:
    """Render generated YAML materials to output files."""
    click.echo("not implemented yet")


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

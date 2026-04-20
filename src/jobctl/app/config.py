"""Configuration command."""

from pathlib import Path
from typing import Annotated

import click
import typer

from jobctl.app.common import command_error, print_config
from jobctl.config import (
    ConfigError,
    find_project_root,
    load_config,
    replace_config_value,
    save_config,
)

app = typer.Typer(help="View or update project configuration.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def config(
    ctx: typer.Context,
    key: Annotated[str | None, typer.Argument(help="Configuration key to update.")] = None,
    value: Annotated[str | None, typer.Argument(help="Configuration value to set.")] = None,
) -> None:
    """View or update project configuration."""
    if ctx.invoked_subcommand is not None:
        return
    if (key is None) != (value is None):
        raise click.UsageError("Provide both KEY and VALUE, or neither.")

    try:
        project_root = find_project_root(Path.cwd())
        loaded_config = load_config(project_root)
        if key is None:
            print_config(loaded_config)
            return

        updated_config = replace_config_value(loaded_config, key, value or "")
        save_config(project_root, updated_config)
        typer.echo(f"Updated {key}.")
    except ConfigError as exc:
        raise command_error(str(exc)) from exc

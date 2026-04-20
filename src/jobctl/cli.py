"""Typer command-line interface for jobctl (v2: single-entry TUI)."""

import logging

import click
import typer

from jobctl.app.common import run_tui
from jobctl.app.config import app as config_app
from jobctl.app.init import app as init_app
from jobctl.app.renderer import app as renderer_app

app = typer.Typer(
    help="AI-powered job search assistant.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-essential output."),
    use_tui: bool = typer.Option(
        False,
        "--tui",
        help="Launch the unified Textual TUI (also the default when no subcommand is given).",
    ),
) -> None:
    """AI-powered job search assistant."""
    if verbose and quiet:
        raise click.UsageError("Use either --verbose or --quiet, not both.")
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    if ctx.invoked_subcommand is not None:
        return
    if use_tui or ctx.invoked_subcommand is None:
        run_tui("chat")


app.add_typer(init_app, name="init")
app.add_typer(config_app, name="config")
app.add_typer(renderer_app, name="render")

main = typer.main.get_command(app)
main.name = "jobctl"

"""Typer command-line interface for jobctl."""

import logging

import click
import typer

from jobctl.app.agent import app as agent_app
from jobctl.app.apply import app as apply_app
from jobctl.app.config import app as config_app
from jobctl.app.init import app as init_app
from jobctl.app.onboard import app as onboard_app
from jobctl.app.profile import app as profile_app
from jobctl.app.renderer import app as renderer_app
from jobctl.app.track import app as track_app
from jobctl.app.yap import app as yap_app

app = typer.Typer(
    help="AI-powered job search assistant.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def root(
    verbose: bool = typer.Option(False, "--verbose", help="Enable debug logging."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-essential output."),
) -> None:
    """AI-powered job search assistant."""
    if verbose and quiet:
        raise click.UsageError("Use either --verbose or --quiet, not both.")
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


app.add_typer(init_app, name="init")
app.add_typer(onboard_app, name="onboard")
app.add_typer(agent_app, name="agent")
app.add_typer(yap_app, name="yap")
app.add_typer(apply_app, name="apply")
app.add_typer(track_app, name="track")
app.add_typer(profile_app, name="profile")
app.add_typer(renderer_app, name="render")
app.add_typer(config_app, name="config")

main = typer.main.get_command(app)
main.name = "jobctl"

"""Deprecated apply command — now launches the TUI apply view."""

from __future__ import annotations

from typing import Annotated

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(
    help="(deprecated) Evaluate and tailor materials.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def apply(
    ctx: typer.Context,
    url: Annotated[
        str | None,
        typer.Argument(help="Job URL or pasted job description."),
    ] = None,
) -> None:
    """Open the TUI apply view; the legacy pipeline is reachable via the agent."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("apply", "jobctl")
    initial = f"Start a new application for: {url}" if url else None
    run_tui(start_screen="apply", initial_message=initial)

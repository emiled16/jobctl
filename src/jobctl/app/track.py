"""Deprecated track command — now launches the TUI tracker view."""

from __future__ import annotations

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(
    help="(deprecated) Open the application tracker.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def track(ctx: typer.Context) -> None:
    """Open or update the application tracker inside the TUI."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("track", "jobctl")
    run_tui(start_screen="tracker")

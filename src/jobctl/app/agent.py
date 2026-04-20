"""Deprecated agent shell — now launches the TUI chat view."""

from __future__ import annotations

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(help="(deprecated) Start the agent shell.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def agent(ctx: typer.Context) -> None:
    """Start the agent shell inside the unified TUI."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("agent", "jobctl")
    run_tui(start_screen="chat")

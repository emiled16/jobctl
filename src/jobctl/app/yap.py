"""Deprecated yap command — now launches the TUI chat view."""

from __future__ import annotations

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(
    help="(deprecated) Add profile knowledge from notes.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def yap(ctx: typer.Context) -> None:
    """Open the TUI chat view so the agent can ingest freeform notes."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("yap", "jobctl")
    run_tui(
        start_screen="chat",
        initial_message="I want to add some freeform notes to my profile.",
    )

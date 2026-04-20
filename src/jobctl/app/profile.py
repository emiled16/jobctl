"""Deprecated profile command — now launches the TUI graph view."""

from __future__ import annotations

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(
    help="(deprecated) Inspect the stored career profile.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def profile(ctx: typer.Context) -> None:
    """Inspect the stored career profile inside the TUI graph view."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("profile", "jobctl")
    run_tui(start_screen="graph")

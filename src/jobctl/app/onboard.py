"""Deprecated onboarding command — now launches the TUI chat view."""

from __future__ import annotations

import typer

from jobctl.app.common import deprecation_warning, run_tui

app = typer.Typer(help="(deprecated) Start onboarding.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def onboard(ctx: typer.Context) -> None:
    """Start the onboarding conversation inside the TUI chat view."""
    if ctx.invoked_subcommand is not None:
        return
    deprecation_warning("onboard", "jobctl")
    run_tui(
        start_screen="chat",
        initial_message=(
            "Hi! Let's get your profile set up. "
            "I can ingest your resume or your GitHub repositories — which would you like to start with?"
        ),
    )

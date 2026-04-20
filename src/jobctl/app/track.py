"""Application tracker command."""

import typer

from jobctl.app.common import run_tui

app = typer.Typer(help="Open the application tracker.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def track(ctx: typer.Context) -> None:
    """Open or update the application tracker."""
    if ctx.invoked_subcommand is not None:
        return
    run_tui(start_screen="tracker")

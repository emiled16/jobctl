"""Profile inspector command."""

import typer

from jobctl.app.common import run_tui

app = typer.Typer(help="Inspect the stored career profile.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def profile(ctx: typer.Context) -> None:
    """Inspect the stored career profile."""
    if ctx.invoked_subcommand is not None:
        return
    run_tui(start_screen="graph")

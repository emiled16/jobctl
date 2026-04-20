"""Freeform profile knowledge command."""

from pathlib import Path

import typer

from jobctl.app.common import command_error
from jobctl.config import CONFIG_DIR_NAME, ConfigError, find_project_root, load_config

app = typer.Typer(help="Add profile knowledge from notes.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def yap(ctx: typer.Context) -> None:
    """Add profile knowledge from freeform notes."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.conversation.yap import run_yap
        from jobctl.db.connection import get_connection
        from jobctl.llm.client import LLMClient

        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        llm_client = LLMClient(
            api_key=config.openai_api_key,
            model=config.llm_model,
            cwd=project_root,
        )
        conn = get_connection(db_path)
        try:
            run_yap(conn, llm_client)
        finally:
            conn.close()
    except KeyboardInterrupt:
        typer.echo("\nYap session interrupted. Progress has been saved.")
    except ConfigError as exc:
        raise command_error(str(exc)) from exc

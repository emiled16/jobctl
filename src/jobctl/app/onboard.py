"""Onboarding command."""

from pathlib import Path

import typer

from jobctl.app.common import command_error
from jobctl.config import CONFIG_DIR_NAME, ConfigError, find_project_root, load_config

app = typer.Typer(help="Start onboarding.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def onboard(ctx: typer.Context) -> None:
    """Start the onboarding conversation."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.conversation.onboard import run_onboarding
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
            run_onboarding(conn, llm_client, config)
        finally:
            conn.close()
    except ConfigError as exc:
        raise command_error(str(exc)) from exc

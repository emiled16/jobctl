"""Interactive agent shell command."""

from pathlib import Path

import typer

from jobctl.app.common import command_error
from jobctl.config import CONFIG_DIR_NAME, ConfigError, find_project_root, load_config

app = typer.Typer(help="Start the agent shell.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def agent(ctx: typer.Context) -> None:
    """Start the interactive agent shell."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from jobctl.conversation.agent import run_agent_shell
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
            run_agent_shell(conn, llm_client, config, project_root)
        finally:
            conn.close()
    except KeyboardInterrupt:
        typer.echo("\nAgent session interrupted.")
    except ConfigError as exc:
        raise command_error(str(exc)) from exc

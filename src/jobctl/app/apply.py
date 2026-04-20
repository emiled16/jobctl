"""Application tailoring command."""

from pathlib import Path
from typing import Annotated
import sqlite3

import typer

from jobctl.app.common import command_error
from jobctl.config import CONFIG_DIR_NAME, ConfigError, find_project_root, load_config

app = typer.Typer(help="Evaluate and tailor materials.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def apply(
    ctx: typer.Context,
    url: Annotated[str | None, typer.Argument(help="Job URL or pasted job description.")] = None,
) -> None:
    """Evaluate and tailor materials for a job URL."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        project_root = find_project_root(Path.cwd())
        config = load_config(project_root)
        from rich.prompt import Prompt

        from jobctl.db.connection import get_connection
        from jobctl.jobs.apply_pipeline import run_apply
        from jobctl.llm.client import LLMClient

        url_or_text = url or Prompt.ask("Job URL or pasted JD")
        db_path = project_root / CONFIG_DIR_NAME / "jobctl.db"
        llm_client = LLMClient(
            api_key=config.openai_api_key,
            model=config.llm_model,
            cwd=project_root,
        )
        conn = get_connection(db_path)
        try:
            run_apply(conn, url_or_text, llm_client, config)
        finally:
            conn.close()
    except KeyboardInterrupt:
        typer.echo("\nApply interrupted. Any completed tracker updates have been saved.")
    except ConfigError as exc:
        raise command_error(str(exc)) from exc
    except sqlite3.Error as exc:
        raise command_error(f"SQLite error. Run `jobctl init` first if needed. {exc}") from exc

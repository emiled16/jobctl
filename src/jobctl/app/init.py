"""Project initialization command."""

from pathlib import Path

import typer

from jobctl.app.common import command_error, copy_bundled_templates
from jobctl.config import CONFIG_DIR_NAME, default_config, save_config

app = typer.Typer(help="Initialize a jobctl project.", invoke_without_command=True)


@app.callback(invoke_without_command=True)
def init_command(ctx: typer.Context) -> None:
    """Initialize a jobctl project in the current directory."""
    if ctx.invoked_subcommand is not None:
        return

    project_root = Path.cwd()
    jobctl_dir = project_root / CONFIG_DIR_NAME

    if jobctl_dir.exists():
        raise command_error(f"{CONFIG_DIR_NAME}/ already exists in {project_root}")

    (jobctl_dir / "templates" / "resume").mkdir(parents=True)
    (jobctl_dir / "templates" / "cover-letters").mkdir(parents=True)
    (jobctl_dir / "exports").mkdir()
    copy_bundled_templates(jobctl_dir / "templates")
    save_config(project_root, default_config())

    typer.echo("Initialized .jobctl/. Next, run `jobctl config openai_api_key <key>`.")

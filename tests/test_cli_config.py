from pathlib import Path

import yaml
from click.testing import CliRunner

from jobctl.cli import main
from jobctl.config import JobctlConfig, find_project_root, load_config


def test_init_creates_jobctl_directory_and_default_config(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        isolated_result = runner.invoke(main, ["init"], catch_exceptions=False)
        isolated_path = Path(isolated_dir)

        assert isolated_result.exit_code == 0
        assert (isolated_path / ".jobctl" / "config.yaml").is_file()
        assert (isolated_path / ".jobctl" / "templates").is_dir()
        assert (isolated_path / ".jobctl" / "templates" / "resume").is_dir()
        assert (isolated_path / ".jobctl" / "templates" / "cover-letters").is_dir()
        assert (isolated_path / ".jobctl" / "exports").is_dir()
        assert load_config(isolated_path) == JobctlConfig(
            openai_api_key="",
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            llm_model="gpt-5.4",
            default_template="emile-resume.html",
        )


def test_config_updates_known_value_and_masks_api_key(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        runner.invoke(main, ["init"], catch_exceptions=False)
        update_result = runner.invoke(
            main,
            ["config", "openai_api_key", "sk-test-123456"],
            catch_exceptions=False,
        )
        view_result = runner.invoke(main, ["config"], catch_exceptions=False)

        assert update_result.exit_code == 0
        assert "Updated openai_api_key." in update_result.output
        assert load_config(Path(isolated_dir)).openai_api_key == "sk-test-123456"
        assert "3456" in view_result.output
        assert "sk-test-123456" not in view_result.output


def test_config_rejects_unknown_key(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(main, ["init"], catch_exceptions=False)
        result = runner.invoke(main, ["config", "unknown", "value"])

        assert result.exit_code != 0
        assert "Unknown config key" in result.output


def test_find_project_root_walks_up_from_nested_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "a" / "b"
    nested.mkdir(parents=True)
    (project_root / ".jobctl").mkdir()
    (project_root / ".jobctl" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "openai_api_key": "",
                "embedding_model": "text-embedding-3-small",
                "llm_model": "gpt-5.4",
                "default_template": "resume.html",
            }
        ),
        encoding="utf-8",
    )

    assert find_project_root(nested) == project_root

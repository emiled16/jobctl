from pathlib import Path

import yaml
from click.testing import CliRunner

from jobctl.cli import main
from jobctl.config import JobctlConfig, default_config, find_project_root, load_config


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
        assert load_config(isolated_path) == default_config()


def test_config_updates_nested_llm_value(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path) as isolated_dir:
        runner.invoke(main, ["init"], catch_exceptions=False)
        update_result = runner.invoke(
            main,
            ["config", "llm.provider", "openai"],
            catch_exceptions=False,
        )
        view_result = runner.invoke(main, ["config"], catch_exceptions=False)

        assert update_result.exit_code == 0
        assert "Updated llm.provider." in update_result.output
        assert load_config(Path(isolated_dir)).llm.provider == "openai"
        assert "openai" in view_result.output


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
                "llm": {
                    "provider": "codex",
                    "chat_model": "gpt-5.4",
                    "embedding_model": "text-embedding-3-small",
                },
                "default_template": "resume.html",
            }
        ),
        encoding="utf-8",
    )

    assert find_project_root(nested) == project_root


def test_load_config_migrates_legacy_flat_keys(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / ".jobctl").mkdir(parents=True)
    (project_root / ".jobctl" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "openai_api_key": "sk-demo",
                "embedding_model": "text-embedding-3-small",
                "llm_model": "gpt-5.4",
                "default_template": "resume.html",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config(project_root)
    assert isinstance(loaded, JobctlConfig)
    assert loaded.llm.provider == "openai"
    assert loaded.llm.chat_model == "gpt-5.4"
    assert loaded.llm.embedding_model == "text-embedding-3-small"
    assert loaded.default_template == "resume.html"

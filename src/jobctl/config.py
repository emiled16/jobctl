"""Configuration loading and persistence for jobctl projects."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR_NAME = ".jobctl"
CONFIG_FILE_NAME = "config.yaml"
DEFAULT_CONFIG = {
    "openai_api_key": "",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "llm_model": "gpt-5.4",
    "default_template": "emile-resume.html",
}


class ConfigError(Exception):
    """Base error for invalid or missing jobctl configuration."""


class ProjectNotFoundError(ConfigError):
    """Raised when no .jobctl project directory exists above a path."""


class ConfigValidationError(ConfigError):
    """Raised when config.yaml is missing required fields or has invalid data."""


@dataclass(frozen=True)
class JobctlConfig:
    openai_api_key: str
    embedding_model: str
    llm_model: str
    default_template: str


def default_config() -> JobctlConfig:
    return JobctlConfig(**DEFAULT_CONFIG)


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / CONFIG_DIR_NAME).is_dir():
            return candidate

    raise ProjectNotFoundError(f"No {CONFIG_DIR_NAME} directory found from {start}")


def load_config(project_root: Path) -> JobctlConfig:
    config_path = _config_path(project_root)
    if not config_path.exists():
        raise ConfigValidationError(f"Missing config file: {config_path}")

    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_config, dict):
        raise ConfigValidationError("config.yaml must contain a mapping")

    return _validate_config(raw_config)


def save_config(project_root: Path, config: JobctlConfig) -> None:
    config_path = _config_path(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")


def config_field_names() -> tuple[str, ...]:
    return tuple(JobctlConfig.__dataclass_fields__)


def replace_config_value(config: JobctlConfig, key: str, value: str) -> JobctlConfig:
    if key not in config_field_names():
        raise ConfigValidationError(f"Unknown config key: {key}")

    values = asdict(config)
    values[key] = value
    return JobctlConfig(**values)


def _config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _validate_config(raw_config: dict[str, Any]) -> JobctlConfig:
    missing_fields = [field for field in config_field_names() if field not in raw_config]
    if missing_fields:
        joined_fields = ", ".join(missing_fields)
        raise ConfigValidationError(f"Missing required config field(s): {joined_fields}")

    values: dict[str, str] = {}
    for field in config_field_names():
        value = raw_config[field]
        if not isinstance(value, str):
            raise ConfigValidationError(f"Config field {field!r} must be a string")
        values[field] = value

    return JobctlConfig(**values)

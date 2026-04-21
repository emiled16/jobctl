"""Configuration loading and persistence for jobctl projects."""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR_NAME = ".jobctl"
CONFIG_FILE_NAME = "config.yaml"

VALID_PROVIDERS = ("openai", "ollama", "codex")
VALID_VECTOR_PROVIDERS = ("qdrant",)
VALID_VECTOR_MODES = ("local", "remote")
VALID_VECTOR_DISTANCES = ("cosine", "dot", "euclid")


class ConfigError(Exception):
    """Base error for invalid or missing jobctl configuration."""


class ProjectNotFoundError(ConfigError):
    """Raised when no .jobctl project directory exists above a path."""


class ConfigValidationError(ConfigError):
    """Raised when config.yaml is missing required fields or has invalid data."""


@dataclass(frozen=True)
class OpenAIConfig:
    api_key_env: str = "OPENAI_API_KEY"


@dataclass(frozen=True)
class OllamaConfig:
    host: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "codex"
    chat_model: str = "gpt-5.4"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)


@dataclass(frozen=True)
class VectorStoreConfig:
    provider: str = "qdrant"
    mode: str = "local"
    path: str = ".jobctl/qdrant"
    url: str = ""
    api_key_env: str = "QDRANT_API_KEY"
    collection: str = "jobctl_nodes"
    distance: str = "cosine"


@dataclass(frozen=True)
class JobctlConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    default_template: str = "emile-resume.html"

    # Backward-compatibility shims for the v1 flat keys. New code should
    # read from the nested ``llm`` block directly.
    @property
    def openai_api_key(self) -> str:
        import os

        return os.environ.get(self.llm.openai.api_key_env, "")

    @property
    def llm_model(self) -> str:
        return self.llm.chat_model

    @property
    def embedding_model(self) -> str:
        return self.llm.embedding_model


def default_config() -> JobctlConfig:
    return JobctlConfig()


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

    raw_config = _migrate_flat_config(raw_config)
    return _validate_config(raw_config)


def save_config(project_root: Path, config: JobctlConfig) -> None:
    config_path = _config_path(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")


def replace_config_value(config: JobctlConfig, key: str, value: str) -> JobctlConfig:
    """Set a dotted-path config key (``llm.provider``, ``default_template``, …)."""
    parts = key.split(".")
    return _set_dotted(config, parts, value)


def _set_dotted(obj: Any, path: list[str], value: str) -> Any:
    head, *rest = path
    fields = {f.name for f in obj.__dataclass_fields__.values()}
    if head not in fields:
        raise ConfigValidationError(f"Unknown config key: {head}")
    current = getattr(obj, head)
    if not rest:
        if hasattr(current, "__dataclass_fields__"):
            raise ConfigValidationError(
                f"Config key {head!r} is a group; use a dotted path like '{head}.<field>'."
            )
        return replace(obj, **{head: _coerce(type(current), value)})
    if not hasattr(current, "__dataclass_fields__"):
        raise ConfigValidationError(f"Config key {head!r} is not a group")
    return replace(obj, **{head: _set_dotted(current, rest, value)})


def _coerce(target_type: type, value: str) -> Any:
    if target_type is str:
        return value
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is bool:
        return value.lower() in {"1", "true", "yes", "on"}
    return value


def _config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _migrate_flat_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Map old flat config keys to the new nested ``llm.*`` structure."""
    flat_keys = {"openai_api_key", "embedding_model", "llm_model"}
    if not flat_keys.intersection(raw):
        return raw

    print(
        "jobctl: migrating legacy flat LLM config keys; run 'jobctl config' to persist.",
        file=sys.stderr,
    )

    migrated = {k: v for k, v in raw.items() if k not in flat_keys}
    llm_section = dict(raw.get("llm") or {})
    if "llm_model" in raw and "chat_model" not in llm_section:
        llm_section["chat_model"] = raw["llm_model"]
    if "embedding_model" in raw and "embedding_model" not in llm_section:
        llm_section["embedding_model"] = raw["embedding_model"]
    if "openai_api_key" in raw:
        openai_section = dict(llm_section.get("openai") or {})
        openai_section.setdefault("api_key_env", "OPENAI_API_KEY")
        llm_section["openai"] = openai_section
        llm_section.setdefault("provider", "openai" if raw["openai_api_key"] else "codex")
    else:
        llm_section.setdefault("provider", "codex")
    migrated["llm"] = llm_section
    migrated.setdefault("default_template", raw.get("default_template", "emile-resume.html"))
    return migrated


def _validate_config(raw: dict[str, Any]) -> JobctlConfig:
    llm_raw = raw.get("llm") or {}
    if not isinstance(llm_raw, dict):
        raise ConfigValidationError("llm block must be a mapping")

    provider = str(llm_raw.get("provider") or "codex")
    if provider not in VALID_PROVIDERS:
        raise ConfigValidationError(
            f"llm.provider must be one of {VALID_PROVIDERS!r}, got {provider!r}"
        )

    openai_raw = llm_raw.get("openai") or {}
    if not isinstance(openai_raw, dict):
        raise ConfigValidationError("llm.openai must be a mapping")
    openai_cfg = OpenAIConfig(
        api_key_env=str(openai_raw.get("api_key_env") or "OPENAI_API_KEY"),
    )

    ollama_raw = llm_raw.get("ollama") or {}
    if not isinstance(ollama_raw, dict):
        raise ConfigValidationError("llm.ollama must be a mapping")
    ollama_cfg = OllamaConfig(
        host=str(ollama_raw.get("host") or "http://localhost:11434"),
        embedding_model=str(ollama_raw.get("embedding_model") or "nomic-embed-text"),
    )

    llm_cfg = LLMConfig(
        provider=provider,
        chat_model=str(llm_raw.get("chat_model") or "gpt-5.4"),
        embedding_model=str(
            llm_raw.get("embedding_model") or "sentence-transformers/all-MiniLM-L6-v2"
        ),
        openai=openai_cfg,
        ollama=ollama_cfg,
    )

    vector_raw = raw.get("vector_store") or {}
    if not isinstance(vector_raw, dict):
        raise ConfigValidationError("vector_store block must be a mapping")
    vector_provider = str(vector_raw.get("provider") or "qdrant")
    if vector_provider not in VALID_VECTOR_PROVIDERS:
        raise ConfigValidationError(
            f"vector_store.provider must be one of {VALID_VECTOR_PROVIDERS!r}, "
            f"got {vector_provider!r}"
        )
    vector_mode = str(vector_raw.get("mode") or "local")
    if vector_mode not in VALID_VECTOR_MODES:
        raise ConfigValidationError(
            f"vector_store.mode must be one of {VALID_VECTOR_MODES!r}, got {vector_mode!r}"
        )
    vector_path = str(vector_raw.get("path") or ".jobctl/qdrant")
    vector_url = str(vector_raw.get("url") or "")
    if vector_mode == "local" and not vector_path:
        raise ConfigValidationError("vector_store.path is required when mode is local")
    if vector_mode == "remote" and not vector_url:
        raise ConfigValidationError("vector_store.url is required when mode is remote")
    vector_distance = str(vector_raw.get("distance") or "cosine").lower()
    if vector_distance not in VALID_VECTOR_DISTANCES:
        raise ConfigValidationError(
            f"vector_store.distance must be one of {VALID_VECTOR_DISTANCES!r}, "
            f"got {vector_distance!r}"
        )
    vector_cfg = VectorStoreConfig(
        provider=vector_provider,
        mode=vector_mode,
        path=vector_path,
        url=vector_url,
        api_key_env=str(vector_raw.get("api_key_env") or "QDRANT_API_KEY"),
        collection=str(vector_raw.get("collection") or "jobctl_nodes"),
        distance=vector_distance,
    )

    default_template = str(raw.get("default_template") or "emile-resume.html")

    return JobctlConfig(
        llm=llm_cfg,
        vector_store=vector_cfg,
        default_template=default_template,
    )


def config_field_names() -> tuple[str, ...]:
    """Return the top-level dotted keys supported by ``jobctl config``."""
    return (
        "llm.provider",
        "llm.chat_model",
        "llm.embedding_model",
        "llm.openai.api_key_env",
        "llm.ollama.host",
        "llm.ollama.embedding_model",
        "vector_store.provider",
        "vector_store.mode",
        "vector_store.path",
        "vector_store.url",
        "vector_store.api_key_env",
        "vector_store.collection",
        "vector_store.distance",
        "default_template",
    )

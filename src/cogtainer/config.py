"""Cogtainer configuration: load cogtainers.yml and resolve names."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_GLOBAL_CONFIG_PATH = Path.home() / ".cogos" / "cogtainers.yml"
_LOCAL_CONFIG_NAME = "cogtainers.yml"
_LOCAL_DATA_DIR = "data"


class LLMConfig(BaseModel):
    """LLM provider configuration for a cogtainer."""

    provider: str
    model: str
    api_key_env: str


class CogtainerEntry(BaseModel):
    """A single cogtainer definition."""

    type: str  # "aws" | "local" | "docker"
    region: str | None = None
    account_id: str | None = None
    profile: str | None = None
    domain: str | None = None
    image: str | None = None
    llm: LLMConfig
    dashboard_be_port: int | None = None
    dashboard_fe_port: int | None = None
    tick_interval: int = 60


class DefaultsConfig(BaseModel):
    """Default selections."""

    cogtainer: str | None = None


class CogtainersConfig(BaseModel):
    """Top-level cogtainers.yml schema."""

    cogtainers: dict[str, CogtainerEntry] = Field(default_factory=dict)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


def local_data_dir() -> Path:
    """Return the local data directory (``./data/``)."""
    return Path.cwd() / _LOCAL_DATA_DIR


def local_config_path() -> Path:
    """Return the local config file path (``./data/cogtainers.yml``)."""
    return local_data_dir() / _LOCAL_CONFIG_NAME


def global_config_path() -> Path:
    """Return the global config file path (``~/.cogos/cogtainers.yml``)."""
    env = os.environ.get("COGOS_CONFIG_PATH")
    if env:
        return Path(env)
    return _GLOBAL_CONFIG_PATH


def _load_yaml(path: Path) -> CogtainersConfig:
    """Load a single cogtainers config from YAML."""
    if not path.is_file():
        return CogtainersConfig()
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        return CogtainersConfig()
    return CogtainersConfig.model_validate(data)


def load_config(path: Path | None = None) -> CogtainersConfig:
    """Load and merge cogtainers config from global and local YAML files.

    When *path* is given (e.g. in tests), only that single file is loaded.
    Otherwise, loads ``~/.cogos/cogtainers.yml`` (AWS entries) and
    ``./data/cogtainers.yml`` (local/docker entries) and merges them.
    Defaults come from the local file only.
    """
    if path is not None:
        return _load_yaml(path)

    global_cfg = _load_yaml(global_config_path())
    local_cfg = _load_yaml(local_config_path())

    merged = CogtainersConfig()

    # Global entries (AWS only — local/docker entries belong in ./data/cogtainers.yml)
    for name, entry in global_cfg.cogtainers.items():
        if entry.type in ("local", "docker"):
            logger.warning(
                "Skipping local/docker entry '%s' from global config — "
                "use ./data/cogtainers.yml for local cogtainers",
                name,
            )
            continue
        merged.cogtainers[name] = entry

    # Local entries overlay global ones
    for name, entry in local_cfg.cogtainers.items():
        if entry.type == "aws":
            logger.warning(
                "Skipping AWS entry '%s' from local config — "
                "use ~/.cogos/cogtainers.yml for AWS cogtainers",
                name,
            )
            continue
        merged.cogtainers[name] = entry

    # Defaults from local file only
    merged.defaults = local_cfg.defaults

    return merged


def _read_dotenv_var(key: str) -> str | None:
    """Read a variable from the repo-local .env file.

    Skipped when COGOS_CONFIG_PATH is set (e.g. in tests) to avoid
    the repo .env leaking values into a non-default config context.
    """
    if os.environ.get("COGOS_CONFIG_PATH"):
        return None
    try:
        from cli.local_dev import _read_repo_env, repo_root

        values = _read_repo_env(repo_root() / ".env")
        return values.get(key)
    except Exception:
        return None


_CANONICAL_ENV_VARS = {"COGTAINER", "COGENT"}


def _publish(env_var: str, value: str) -> None:
    """Set a resolved name into os.environ so downstream code can find it."""
    if env_var in _CANONICAL_ENV_VARS:
        os.environ.setdefault(env_var, value)


def resolve_cogtainer_name(
    cfg: CogtainersConfig,
    env_var: str = "COGTAINER",
) -> str:
    """Resolve which cogtainer to use.

    Resolution order:
    1. Environment variable (env_var)
    2. .env file in repo root
    3. Auto-select if only one cogtainer is defined
    4. defaults.cogtainer from config
    5. Raise ValueError

    Sets the resolved name into os.environ so downstream code
    (e.g. cogtainer_key()) can find it without re-resolving.
    """
    from_env = os.environ.get(env_var) or _read_dotenv_var(env_var)
    if from_env:
        _publish(env_var, from_env)
        return from_env

    name: str | None = None
    if len(cfg.cogtainers) == 1:
        name = next(iter(cfg.cogtainers))
    elif cfg.defaults.cogtainer:
        name = cfg.defaults.cogtainer

    if name:
        _publish(env_var, name)
        return name

    names = ", ".join(sorted(cfg.cogtainers.keys()))
    raise ValueError(
        f"Cannot determine cogtainer: multiple defined ({names}) "
        f"with no default set and ${env_var} not in environment."
    )


def resolve_cogent_name(
    available: list[str],
    env_var: str = "COGENT",
) -> str:
    """Resolve which cogent to use.

    Resolution order:
    1. Environment variable (env_var)
    2. .env file in repo root
    3. Auto-select if only one cogent is available
    4. Raise ValueError

    Sets the resolved name into os.environ so downstream code
    can find it without re-resolving.
    """
    from_env = os.environ.get(env_var) or _read_dotenv_var(env_var)
    if from_env:
        _publish(env_var, from_env)
        return from_env

    if len(available) == 1:
        _publish(env_var, available[0])
        return available[0]

    names = ", ".join(sorted(available))
    raise ValueError(
        f"Cannot determine cogent: multiple available ({names}) "
        f"and ${env_var} not in environment."
    )

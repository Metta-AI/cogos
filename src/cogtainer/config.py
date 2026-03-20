"""Cogtainer configuration: load cogtainers.yml and resolve names."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_DEFAULT_CONFIG_PATH = Path.home() / ".cogos" / "cogtainers.yml"


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
    domain: str | None = None
    data_dir: str | None = None
    image: str | None = None
    llm: LLMConfig | None = None


class DefaultsConfig(BaseModel):
    """Default selections."""

    cogtainer: str | None = None


class CogtainersConfig(BaseModel):
    """Top-level cogtainers.yml schema."""

    cogtainers: dict[str, CogtainerEntry] = Field(default_factory=dict)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


def load_config(path: Path | None = None) -> CogtainersConfig:
    """Load cogtainers config from YAML.

    If the file does not exist or is empty, returns an empty config.
    """
    path = path or _DEFAULT_CONFIG_PATH
    if not path.is_file():
        return CogtainersConfig()
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        return CogtainersConfig()
    return CogtainersConfig.model_validate(data)


def resolve_cogtainer_name(
    cfg: CogtainersConfig,
    env_var: str = "COGTAINER",
) -> str:
    """Resolve which cogtainer to use.

    Resolution order:
    1. Environment variable (env_var)
    2. Auto-select if only one cogtainer is defined
    3. defaults.cogtainer from config
    4. Raise ValueError
    """
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env

    if len(cfg.cogtainers) == 1:
        return next(iter(cfg.cogtainers))

    if cfg.defaults.cogtainer:
        return cfg.defaults.cogtainer

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
    2. Auto-select if only one cogent is available
    3. Raise ValueError
    """
    from_env = os.environ.get(env_var)
    if from_env:
        return from_env

    if len(available) == 1:
        return available[0]

    names = ", ".join(sorted(available))
    raise ValueError(
        f"Cannot determine cogent: multiple available ({names}) "
        f"and ${env_var} not in environment."
    )

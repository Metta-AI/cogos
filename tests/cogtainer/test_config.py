"""Tests for cogtainer config loader and name resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cogtainer.config import (
    CogtainersConfig,
    load_config,
    resolve_cogent_name,
    resolve_cogtainer_name,
)

SAMPLE_YAML = textwrap.dedent("""\
    cogtainers:
      prod-aws:
        type: aws
        region: us-east-1
        account_id: "123456789012"
        domain: example.com
        llm:
          provider: bedrock
          model: claude-sonnet-4-20250514
          api_key_env: AWS_ACCESS_KEY_ID
      dev-local:
        type: local
        data_dir: /tmp/cogents
        llm:
          provider: anthropic
          model: claude-sonnet-4-20250514
          api_key_env: ANTHROPIC_API_KEY
    defaults:
      cogtainer: prod-aws
""")


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "cogtainers.yml"
    p.write_text(SAMPLE_YAML)
    return p


# ── load_config ──────────────────────────────────────────────────────

def test_load_cogtainers_from_yaml(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert isinstance(cfg, CogtainersConfig)
    assert set(cfg.cogtainers.keys()) == {"prod-aws", "dev-local"}

    aws = cfg.cogtainers["prod-aws"]
    assert aws.type == "aws"
    assert aws.region == "us-east-1"
    assert aws.account_id == "123456789012"
    assert aws.domain == "example.com"
    assert aws.llm.provider == "bedrock"

    local = cfg.cogtainers["dev-local"]
    assert local.type == "local"
    assert local.data_dir == "/tmp/cogents"

    assert cfg.defaults.cogtainer == "prod-aws"


def test_empty_config_file(tmp_path: Path) -> None:
    p = tmp_path / "cogtainers.yml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg.cogtainers == {}
    assert cfg.defaults.cogtainer is None


def test_missing_config_file(tmp_path: Path) -> None:
    p = tmp_path / "nonexistent.yml"
    cfg = load_config(p)
    assert cfg.cogtainers == {}


# ── resolve_cogtainer_name ───────────────────────────────────────────

def test_resolve_cogtainer_from_env(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config(config_file)
    monkeypatch.setenv("COGTAINER", "dev-local")
    assert resolve_cogtainer_name(cfg) == "dev-local"


def test_resolve_auto_selects_single(tmp_path: Path) -> None:
    p = tmp_path / "cogtainers.yml"
    p.write_text(textwrap.dedent("""\
        cogtainers:
          only-one:
            type: local
            data_dir: /tmp/x
            llm:
              provider: anthropic
              model: claude-sonnet-4-20250514
              api_key_env: ANTHROPIC_API_KEY
    """))
    cfg = load_config(p)
    # No env var, no default — should auto-select the single entry
    name = resolve_cogtainer_name(cfg, env_var="_COGTAINER_TEST_UNUSED")
    assert name == "only-one"


def test_resolve_errors_on_ambiguous(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config(config_file)
    # Remove the default so resolution is ambiguous
    cfg.defaults.cogtainer = None
    monkeypatch.delenv("COGTAINER", raising=False)
    with pytest.raises(ValueError, match="[Aa]mbiguous|[Cc]annot determine"):
        resolve_cogtainer_name(cfg, env_var="_COGTAINER_TEST_UNUSED")


def test_resolve_cogtainer_uses_default(config_file: Path) -> None:
    cfg = load_config(config_file)
    name = resolve_cogtainer_name(cfg, env_var="_COGTAINER_TEST_UNUSED")
    assert name == "prod-aws"


# ── resolve_cogent_name ──────────────────────────────────────────────

def test_resolve_cogent_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGENT", "my-cogent")
    assert resolve_cogent_name(["a", "b"]) == "my-cogent"


def test_resolve_cogent_name_auto_selects_single() -> None:
    name = resolve_cogent_name(["solo"], env_var="_COGENT_TEST_UNUSED")
    assert name == "solo"


def test_resolve_cogent_name_errors_on_ambiguous() -> None:
    with pytest.raises(ValueError, match="[Aa]mbiguous|[Cc]annot determine"):
        resolve_cogent_name(["a", "b"], env_var="_COGENT_TEST_UNUSED")


# ── tick_interval ────────────────────────────────────────────────────

def test_tick_interval_defaults_to_60() -> None:
    from cogtainer.config import CogtainerEntry, LLMConfig

    entry = CogtainerEntry(
        type="local",
        data_dir="/tmp/x",
        llm=LLMConfig(provider="anthropic", model="test", api_key_env=""),
    )
    assert entry.tick_interval == 60


def test_tick_interval_custom_value(tmp_path: Path) -> None:
    p = tmp_path / "cogtainers.yml"
    p.write_text(textwrap.dedent("""\
        cogtainers:
          fast:
            type: local
            data_dir: /tmp/x
            tick_interval: 10
            llm:
              provider: anthropic
              model: test
              api_key_env: KEY
    """))
    cfg = load_config(p)
    assert cfg.cogtainers["fast"].tick_interval == 10

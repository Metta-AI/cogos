"""Tests for cogtainer CLI commands."""

from __future__ import annotations

from unittest.mock import patch

import yaml
from click.testing import CliRunner

from cogtainer.cogtainer_cli import cli


def _read_config(path):
    return yaml.safe_load(path.read_text())


def test_cogtainer_create_local(tmp_path, monkeypatch):
    """Local cogtainers are saved to ./data/cogtainers.yml."""
    global_config = tmp_path / "global" / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "create", "dev",
        "--type", "local",
        "--llm-provider", "anthropic",
        "--llm-model", "claude-sonnet-4-20250514",
        "--llm-api-key-env", "ANTHROPIC_API_KEY",
    ], input="\n" * 10)
    assert result.exit_code == 0, result.output

    local_config = tmp_path / "data" / "cogtainers.yml"
    assert local_config.is_file()
    cfg = _read_config(local_config)
    assert "dev" in cfg["cogtainers"]
    entry = cfg["cogtainers"]["dev"]
    assert entry["type"] == "local"
    assert entry["llm"]["provider"] == "anthropic"
    # Only local cogtainer -> set as default
    assert cfg["defaults"]["cogtainer"] == "dev"
    # Data dir created
    assert (tmp_path / "data").is_dir()


def test_cogtainer_create_aws(tmp_path, monkeypatch):
    """AWS cogtainers are saved to the global config."""
    global_config = tmp_path / "global" / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))
    monkeypatch.chdir(tmp_path)

    with patch("cogtainer.cogtainer_cli._cdk_create_account", return_value="111222333444"):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "create", "prod",
            "--type", "aws",
            "--region", "us-west-2",
        ], input="\n" * 10)

    assert result.exit_code == 0, result.output

    cfg = _read_config(global_config)
    assert "prod" in cfg["cogtainers"]
    entry = cfg["cogtainers"]["prod"]
    assert entry["type"] == "aws"
    assert entry["account_id"] == "111222333444"
    assert entry["region"] == "us-west-2"


def test_cogtainer_create_aws_default_region(tmp_path, monkeypatch):
    global_config = tmp_path / "global" / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))
    monkeypatch.chdir(tmp_path)

    with patch("cogtainer.cogtainer_cli._cdk_create_account", return_value="999888777666") as mock:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "create", "prod",
            "--type", "aws",
        ], input="\n" * 10)

    assert result.exit_code == 0, result.output
    mock.assert_called_once_with("prod", region="us-east-1", profile=None)

    cfg = _read_config(global_config)
    assert cfg["cogtainers"]["prod"]["account_id"] == "999888777666"
    assert cfg["cogtainers"]["prod"]["region"] == "us-east-1"


def test_cogtainer_list_empty(tmp_path, monkeypatch):
    global_config = tmp_path / "global" / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "No cogtainers" in result.output


def test_cogtainer_list_shows_entries(tmp_path, monkeypatch):
    """List merges entries from both global and local configs."""
    global_config = tmp_path / "global" / "cogtainers.yml"
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text(yaml.dump({
        "cogtainers": {
            "prod": {
                "type": "aws",
                "region": "us-east-1",
                "llm": {
                    "provider": "bedrock",
                    "model": "anthropic.claude-3-sonnet",
                    "api_key_env": "NONE",
                },
            },
        },
    }))
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))

    local_dir = tmp_path / "project" / "data"
    local_dir.mkdir(parents=True)
    local_config = local_dir / "cogtainers.yml"
    local_config.write_text(yaml.dump({
        "cogtainers": {
            "dev": {
                "type": "local",
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }))
    monkeypatch.chdir(tmp_path / "project")

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "dev" in result.output
    assert "prod" in result.output
    assert "local" in result.output
    assert "aws" in result.output


def test_cogtainer_destroy_local(tmp_path, monkeypatch):
    """Destroying a local cogtainer removes it from the local config."""
    global_config = tmp_path / "global" / "cogtainers.yml"
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(global_config))

    local_dir = tmp_path / "project" / "data"
    local_dir.mkdir(parents=True)
    local_config = local_dir / "cogtainers.yml"
    local_config.write_text(yaml.dump({
        "cogtainers": {
            "dev": {
                "type": "local",
                "llm": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4-20250514",
                    "api_key_env": "ANTHROPIC_API_KEY",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }))
    monkeypatch.chdir(tmp_path / "project")

    runner = CliRunner()
    result = runner.invoke(cli, ["destroy", "dev"], input="y\n")
    assert result.exit_code == 0

    cfg = _read_config(local_config)
    assert "dev" not in cfg["cogtainers"]

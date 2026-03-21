"""Tests for cogent CLI commands."""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from cogtainer.cogent_cli import cli


def _write_local_config(config_path, data_dir):
    """Write a minimal cogtainers.yml with a local cogtainer."""
    cfg = {
        "cogtainers": {
            "dev": {
                "type": "local",
                "data_dir": str(data_dir),
                "llm": {
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                    "api_key_env": "OPENROUTER_API_KEY",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }
    config_path.write_text(yaml.dump(cfg))


def test_cogent_create_local(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    _write_local_config(config_path, data_dir)
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)

    runner = CliRunner()
    result = runner.invoke(cli, ["create", "my-agent"])
    assert result.exit_code == 0, result.output
    assert (data_dir / "my-agent").is_dir()


def test_cogent_list_local(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    _write_local_config(config_path, data_dir)
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)

    # Create cogent dirs manually
    (data_dir / "alpha").mkdir(parents=True)
    (data_dir / "beta").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "beta" in result.output


def test_cogent_destroy_local(tmp_path, monkeypatch):
    config_path = tmp_path / "cogtainers.yml"
    data_dir = tmp_path / "data"
    _write_local_config(config_path, data_dir)
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)

    # Create cogent dir
    (data_dir / "doomed").mkdir(parents=True)
    assert (data_dir / "doomed").is_dir()

    runner = CliRunner()
    result = runner.invoke(cli, ["destroy", "doomed"], input="y\n")
    assert result.exit_code == 0, result.output
    assert not (data_dir / "doomed").exists()

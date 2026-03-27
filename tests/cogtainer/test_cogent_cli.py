"""Tests for cogent CLI commands."""

from __future__ import annotations

from unittest.mock import patch

import yaml
from click.testing import CliRunner

from cogtainer.cogent_cli import cli


def _write_local_config(config_path):
    """Write a minimal cogtainers.yml with a local cogtainer."""
    cfg = {
        "cogtainers": {
            "dev": {
                "type": "local",
                "llm": {
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                    "api_key_env": "OPENROUTER_API_KEY",
                },
            },
        },
        "defaults": {"cogtainer": "dev"},
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(cfg))


def test_cogent_create_local(tmp_path, monkeypatch):
    # Set up local config at ./data/cogtainers.yml
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    _write_local_config(project_dir / "data" / "cogtainers.yml")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)
    monkeypatch.delenv("COGOS_CONFIG_PATH", raising=False)

    runner = CliRunner()
    with patch("cogos.io.google.provisioning.create_service_account"):
        result = runner.invoke(cli, ["create", "my-agent"])
    assert result.exit_code == 0, result.output
    assert (project_dir / "data" / "my-agent").is_dir()


def test_cogent_list_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    _write_local_config(project_dir / "data" / "cogtainers.yml")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)
    monkeypatch.delenv("COGOS_CONFIG_PATH", raising=False)

    # Create cogent dirs manually
    data_dir = project_dir / "data"
    (data_dir / "alpha").mkdir(parents=True)
    (data_dir / "beta").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "beta" in result.output


def test_cogent_destroy_local(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    _write_local_config(project_dir / "data" / "cogtainers.yml")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)
    monkeypatch.delenv("COGOS_CONFIG_PATH", raising=False)

    # Create cogent dir
    data_dir = project_dir / "data"
    (data_dir / "doomed").mkdir(parents=True)
    assert (data_dir / "doomed").is_dir()

    runner = CliRunner()
    with patch("cogos.io.google.provisioning.delete_service_account"):
        result = runner.invoke(cli, ["destroy", "doomed"], input="y\n")
    assert result.exit_code == 0, result.output
    assert not (data_dir / "doomed").exists()

"""End-to-end integration test for the full local cogtainer flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from cogtainer.cogent_cli import cli as cogent_cli
from cogtainer.cogtainer_cli import cli as cogtainer_cli
from cogtainer.config import load_config, resolve_cogtainer_name
from cogtainer.runtime.factory import create_runtime


@patch("cogos.io.google.provisioning.create_service_account")
def test_full_local_flow(_mock_gsa, tmp_path: Path, monkeypatch):
    """End-to-end: create cogtainer -> create cogent -> get repo -> list cogents."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)
    # Point global config to an empty file to avoid loading the real ~/.cogos/cogtainers.yml
    empty_global = tmp_path / "empty_global.yml"
    empty_global.touch()
    monkeypatch.setenv("COGOS_CONFIG_PATH", str(empty_global))
    monkeypatch.delenv("COGTAINER", raising=False)
    monkeypatch.delenv("COGENT", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-fake")

    runner = CliRunner()

    # 1. Create cogtainer via CLI (local type, openrouter)
    result = runner.invoke(cogtainer_cli, [
        "create", "my-local",
        "--type", "local",
        "--llm-provider", "openrouter",
        "--llm-model", "anthropic/claude-sonnet-4-20250514",
        "--llm-api-key-env", "OPENROUTER_API_KEY",
    ], input="\n" * 10)
    assert result.exit_code == 0, result.output
    assert "Created cogtainer 'my-local'" in result.output

    # 2. Create cogent via CLI
    result = runner.invoke(cogent_cli, ["create", "agent-alpha"])
    assert result.exit_code == 0, result.output
    assert "Created cogent 'agent-alpha'" in result.output

    data_dir = project_dir / "data"

    # 3. Verify cogent directory and files/ subdir exist
    assert (data_dir / "agent-alpha").is_dir()
    assert (data_dir / "agent-alpha" / "files").is_dir()

    # 4. Load merged config, resolve cogtainer, create runtime
    cfg = load_config()
    cogtainer_name = resolve_cogtainer_name(cfg)
    assert cogtainer_name == "my-local"
    entry = cfg.cogtainers[cogtainer_name]
    runtime = create_runtime(entry)

    # 5. Verify list_cogents includes the created cogent
    cogents = runtime.list_cogents()
    assert "agent-alpha" in cogents

    # 6. Get repository, verify it's a UnifiedRepository
    repo = runtime.get_repository("agent-alpha")
    from cogos.db.unified_repository import UnifiedRepository

    assert isinstance(repo, UnifiedRepository)

    # 7. Put + get file roundtrip
    content = b"hello cogtainer world"
    key = runtime.put_file("agent-alpha", "test.txt", content)
    assert key == "test.txt"
    retrieved = runtime.get_file("agent-alpha", "test.txt")
    assert retrieved == content

    # 8. Create second cogent, verify both in list
    result = runner.invoke(cogent_cli, ["create", "agent-beta"])
    assert result.exit_code == 0, result.output
    cogents = runtime.list_cogents()
    assert "agent-alpha" in cogents
    assert "agent-beta" in cogents
    assert len(cogents) == 2

    # 9. List cogents via CLI, verify output
    result = runner.invoke(cogent_cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "agent-alpha" in result.output
    assert "agent-beta" in result.output

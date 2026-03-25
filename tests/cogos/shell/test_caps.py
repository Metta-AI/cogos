"""Tests for shell capability commands."""

from cogos.db.models import Capability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.caps import register


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    repo.upsert_capability(Capability(name="procs", description="Process mgmt", enabled=True))
    repo.upsert_capability(Capability(name="secrets", description="Secret store", enabled=False))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_cap_ls(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "cap ls")
    assert output is not None
    assert "files" in output
    assert "procs" in output
    assert "secrets" in output


def test_cap_disable(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "cap disable files")
    cap = repo.get_capability_by_name("files")
    assert cap is not None
    assert not cap.enabled


def test_cap_enable(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "cap enable secrets")
    cap = repo.get_capability_by_name("secrets")
    assert cap is not None
    assert cap.enabled

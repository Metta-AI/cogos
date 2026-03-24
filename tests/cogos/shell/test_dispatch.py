"""Tests for shell command dispatch."""

from cogos.db.sqlite_repository import SqliteRepository
from cogos.shell.commands import CommandRegistry, ShellState


def test_registry_dispatches_known_command(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()

    @reg.register("echo")
    def echo_cmd(state, args):
        return " ".join(args)

    assert reg.dispatch(state, "echo hello world") == "hello world"


def test_registry_returns_error_for_unknown_command(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    result = reg.dispatch(state, "nosuchcmd foo")
    assert result is not None
    assert "unknown command" in result.lower()


def test_registry_handles_empty_input(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    assert reg.dispatch(state, "") == ""


def test_registry_handles_alias(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()

    @reg.register("edit", aliases=["vim"])
    def edit_cmd(state, args):
        return f"editing {args[0]}"

    assert reg.dispatch(state, "vim foo.py") == "editing foo.py"

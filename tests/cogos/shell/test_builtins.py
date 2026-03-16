"""Tests for shell builtins."""

from cogos.db.local_repository import LocalRepository
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.builtins import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)

    @reg.register("dummy", help="A dummy command")
    def dummy(state, args):
        return "ok"

    return state, reg


def test_help_lists_commands(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "help")
    assert "help" in output
    assert "dummy" in output


def test_exit_returns_none(tmp_path):
    state, reg = _setup(tmp_path)
    result = reg.dispatch(state, "exit")
    assert result is None


def test_history_empty(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "history")
    assert "no history" in output.lower()


def test_history_shows_entries(tmp_path):
    from cogos.files.store import FileStore
    state, reg = _setup(tmp_path)
    fs = FileStore(state.repo)
    fs.create("home/root/.shell_history", "ls\nps\ncat foo.md\n")
    output = reg.dispatch(state, "history")
    assert "ls" in output
    assert "ps" in output
    assert "cat foo.md" in output

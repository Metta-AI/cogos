"""Tests for shell file commands."""

from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.files import register


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "init content")
    fs.create("prompts/scheduler.md", "scheduler content")
    fs.create("config/system.yaml", "key: value")
    fs.create("data/logs/run1.txt", "log output")
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg


def test_pwd_at_root(tmp_path):
    state, reg = _setup(tmp_path)
    assert reg.dispatch(state, "pwd") == "/"


def test_ls_root_shows_directories(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "ls")
    assert output is not None
    assert "prompts/" in output
    assert "config/" in output
    assert "data/" in output


def test_ls_prefix_shows_children(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "ls prompts")
    assert output is not None
    assert "init.md" in output
    assert "scheduler.md" in output


def test_cd_and_pwd(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    assert state.cwd == "prompts/"
    assert reg.dispatch(state, "pwd") == "/prompts"


def test_cd_dotdot(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    reg.dispatch(state, "cd ..")
    assert state.cwd == ""


def test_cd_absolute(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    reg.dispatch(state, "cd /config")
    assert state.cwd == "config/"


def test_cat_absolute(tmp_path):
    state, reg = _setup(tmp_path)
    assert reg.dispatch(state, "cat prompts/init.md") == "init content"


def test_cat_relative(tmp_path):
    state, reg = _setup(tmp_path)
    reg.dispatch(state, "cd prompts")
    assert reg.dispatch(state, "cat init.md") == "init content"


def test_cat_not_found(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "cat nope.txt")
    assert output is not None
    assert "not found" in output.lower()


def test_rm(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "rm prompts/init.md")
    assert output is not None
    assert "removed" in output.lower()
    output2 = reg.dispatch(state, "cat prompts/init.md")
    assert output2 is not None
    assert "not found" in output2.lower()


def test_tree(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "tree")
    assert output is not None
    assert "prompts/" in output or "prompts" in output
    assert "init.md" in output
    assert "config/" in output or "config" in output


def test_mkdir_noop(tmp_path):
    state, reg = _setup(tmp_path)
    output = reg.dispatch(state, "mkdir newdir")
    assert output is not None
    assert "implicit" in output.lower()

"""Tests for shell llm command — uses a mock executor."""

from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Capability
from cogos.files.store import FileStore
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.llm import register


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    fs = FileStore(repo)
    fs.create("prompts/hello.md", "Say hello world")
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_llm_creates_temp_process(tmp_path, monkeypatch):
    state, reg, repo = _setup(tmp_path)

    executed = []

    def fake_run_and_complete(process, event_data, run, config, repo, **kwargs):
        executed.append(process.name)
        run.tokens_in = 10
        run.tokens_out = 5
        return run

    monkeypatch.setattr("cogos.shell.commands.llm.run_and_complete", fake_run_and_complete)
    monkeypatch.setattr("cogos.shell.commands.llm.get_config", lambda: None)

    output = reg.dispatch(state, "llm say hi")
    assert len(executed) == 1
    assert executed[0].startswith("shell-")


def test_source_reads_file(tmp_path, monkeypatch):
    state, reg, repo = _setup(tmp_path)

    prompts_seen = []

    def fake_run_and_complete(process, event_data, run, config, repo, **kwargs):
        prompts_seen.append(process.content)
        run.tokens_in = 5
        run.tokens_out = 3
        return run

    monkeypatch.setattr("cogos.shell.commands.llm.run_and_complete", fake_run_and_complete)
    monkeypatch.setattr("cogos.shell.commands.llm.get_config", lambda: None)

    reg.dispatch(state, "source prompts/hello.md")
    assert "Say hello world" in prompts_seen[0]


def test_llm_file_flag(tmp_path, monkeypatch):
    state, reg, repo = _setup(tmp_path)

    prompts_seen = []

    def fake_run_and_complete(process, event_data, run, config, repo, **kwargs):
        prompts_seen.append(process.content)
        run.tokens_in = 5
        run.tokens_out = 3
        return run

    monkeypatch.setattr("cogos.shell.commands.llm.run_and_complete", fake_run_and_complete)
    monkeypatch.setattr("cogos.shell.commands.llm.get_config", lambda: None)

    reg.dispatch(state, "llm -f prompts/hello.md")
    assert "Say hello world" in prompts_seen[0]


def test_llm_help(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "llm --help")
    assert output is not None
    assert "Usage:" in output
    assert "-v" in output
    assert "-f" in output


def test_llm_no_args_shows_help(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "llm")
    assert output is not None
    assert "Usage:" in output

"""Tests for shell tab completer."""

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from cogos.db.models import Capability, Channel, ChannelType, Process, ProcessMode, ProcessStatus
from cogos.db.sqlite_repository import SqliteRepository
from cogos.files.store import FileStore
from cogos.shell.commands import ShellState, build_registry
from cogos.shell.completer import ShellCompleter


def _setup(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    fs = FileStore(repo)
    fs.create("prompts/init.md", "x")
    fs.create("prompts/scheduler.md", "x")
    fs.create("config/system.yaml", "x")
    repo.upsert_process(Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, required_tags=[]))
    repo.upsert_process(Process(
        name="scheduler", mode=ProcessMode.DAEMON,
        status=ProcessStatus.RUNNABLE, required_tags=[],
    ))
    repo.upsert_capability(Capability(name="files", description="File store", enabled=True))
    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    registry = build_registry()
    return state, registry


def _completions(completer, text):
    doc = Document(text, len(text))
    event = CompleteEvent()
    return [c.text for c in completer.get_completions(doc, event)]


def test_completes_command_names(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "p")
    assert "ps" in results
    assert "pwd" in results


def test_completes_file_paths_for_cat(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "cat ")
    assert any("prompts/" in r for r in results)


def test_completes_process_names_for_kill(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "kill ")
    assert "init" in results
    assert "scheduler" in results


def test_completes_subdir_files(tmp_path):
    state, reg = _setup(tmp_path)
    completer = ShellCompleter(state, reg)
    results = _completions(completer, "cat prompts/")
    assert any("init.md" in r for r in results)

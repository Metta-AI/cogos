"""Tests for shell process commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.procs import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_process(Process(name="init", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING, runner="lambda"))
    repo.upsert_process(
        Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda")
    )
    repo.upsert_process(
        Process(name="done-job", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED, runner="lambda")
    )
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_ps_excludes_completed(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ps")
    assert output is not None
    assert "init" in output
    assert "scheduler" in output
    assert "done-job" not in output


def test_ps_all_includes_completed(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ps --all")
    assert output is not None
    assert "done-job" in output


def test_kill_disables(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill scheduler")
    p = repo.get_process_by_name("scheduler")
    assert p is not None
    assert p.status == ProcessStatus.DISABLED


def test_kill_9_disables(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill -9 scheduler")
    p = repo.get_process_by_name("scheduler")
    assert p is not None
    assert p.status == ProcessStatus.DISABLED


def test_kill_hup_restarts(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, "kill -HUP init")
    p = repo.get_process_by_name("init")
    assert p is not None
    assert p.status == ProcessStatus.RUNNABLE


def test_kill_not_found(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "kill nonexistent")
    assert output is not None
    assert "not found" in output.lower()


def test_spawn(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, 'spawn worker --content "do stuff"')
    p = repo.get_process_by_name("worker")
    assert p is not None
    assert p.status == ProcessStatus.RUNNABLE
    assert p.content == "do stuff"

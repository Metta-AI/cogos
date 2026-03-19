"""Tests for shell run commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.runs import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    p = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING, runner="lambda")
    repo.upsert_process(p)
    r = Run(process=p.id, status=RunStatus.COMPLETED, tokens_in=100, tokens_out=50, duration_ms=1200)
    repo.create_run(r)
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo, r


def test_runs_list(tmp_path):
    state, reg, _, r = _setup(tmp_path)
    output = reg.dispatch(state, "runs")
    assert output is not None
    assert "scheduler" in output or str(r.id)[:8] in output


def test_run_show(tmp_path):
    state, reg, _, r = _setup(tmp_path)
    output = reg.dispatch(state, f"run show {r.id}")
    assert output is not None
    assert "100" in output
    assert "1200" in output

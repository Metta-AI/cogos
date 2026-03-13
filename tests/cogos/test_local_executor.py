"""Tests for cogos.runtime.local – run_and_complete helper."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.runtime.local import run_and_complete


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _make_process(repo, *, mode=ProcessMode.ONE_SHOT, max_retries=0) -> Process:
    p = Process(
        name="test-proc",
        mode=mode,
        status=ProcessStatus.RUNNING,
        runner="local",
        max_retries=max_retries,
    )
    repo.upsert_process(p)
    return p


def _make_run(repo, process) -> Run:
    run = Run(process=process.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    return run


def _noop_execute(process, event_data, run, config, repo, **kwargs):
    """Fake executor that succeeds immediately."""
    return run


def _failing_execute(process, event_data, run, config, repo, **kwargs):
    """Fake executor that always raises."""
    raise RuntimeError("boom")


# ---- Tests ----


def test_run_and_complete_success(tmp_path):
    """One-shot process, execute succeeds -> run COMPLETED, process COMPLETED."""
    repo = _repo(tmp_path)
    process = _make_process(repo)
    run = _make_run(repo, process)

    result = run_and_complete(
        process, {}, run, None, repo, execute_fn=_noop_execute,
    )

    assert result.id == run.id
    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo.get_process(process.id).status == ProcessStatus.COMPLETED


def test_run_and_complete_daemon_goes_to_waiting(tmp_path):
    """Daemon process, no pending deliveries -> process goes to WAITING after success."""
    repo = _repo(tmp_path)
    process = _make_process(repo, mode=ProcessMode.DAEMON)
    run = _make_run(repo, process)

    result = run_and_complete(
        process, {}, run, None, repo, execute_fn=_noop_execute,
    )

    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert repo.get_process(process.id).status == ProcessStatus.WAITING


def test_run_and_complete_failure_disables_one_shot(tmp_path):
    """One-shot with max_retries=0, execute raises -> run FAILED, process DISABLED."""
    repo = _repo(tmp_path)
    process = _make_process(repo, max_retries=0)
    run = _make_run(repo, process)

    result = run_and_complete(
        process, {}, run, None, repo, execute_fn=_failing_execute,
    )

    assert repo.get_run(run.id).status == RunStatus.FAILED
    assert repo.get_process(process.id).status == ProcessStatus.DISABLED


def test_run_and_complete_returns_run_on_failure(tmp_path):
    """One-shot with max_retries=1, execute raises -> process RUNNABLE, run returned."""
    repo = _repo(tmp_path)
    process = _make_process(repo, max_retries=1)
    run = _make_run(repo, process)

    result = run_and_complete(
        process, {}, run, None, repo, execute_fn=_failing_execute,
    )

    assert result.id == run.id
    assert repo.get_run(run.id).status == RunStatus.FAILED
    assert repo.get_process(process.id).status == ProcessStatus.RUNNABLE

"""Tests for throttle-aware scheduling."""

from datetime import datetime, timedelta, timezone

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(name=name, mode=ProcessMode.DAEMON, status=status, required_tags=[])


def test_throttled_status_exists():
    """RunStatus.THROTTLED is a valid status."""
    assert RunStatus.THROTTLED == "throttled"


def test_is_throttle_cooldown_active_no_runs(tmp_path):
    """No recent throttled runs means no cooldown."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active

    repo = _repo(tmp_path)
    assert _is_throttle_cooldown_active(repo) is False


def test_is_throttle_cooldown_active_recent_throttle(tmp_path):
    """A recent THROTTLED run triggers cooldown."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active

    repo = _repo(tmp_path)
    proc = _daemon("scheduler", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    run = Run(
        process=proc.id,
        status=RunStatus.THROTTLED,
        error="ThrottlingException",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=60),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=60),
    )
    repo.create_run(run)

    assert _is_throttle_cooldown_active(repo) is True


def test_is_throttle_cooldown_active_old_throttle(tmp_path):
    """A THROTTLED run older than cooldown window returns False."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active

    repo = _repo(tmp_path)
    proc = _daemon("scheduler", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    run = Run(process=proc.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    # Complete it as throttled, then backdate both timestamps
    repo.complete_run(run.id, status=RunStatus.THROTTLED, error="ThrottlingException")
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    stored = repo.get_run(run.id)
    assert stored is not None
    stored.created_at = old_time
    stored.completed_at = old_time

    assert _is_throttle_cooldown_active(repo) is False


def test_failed_run_does_not_trigger_cooldown(tmp_path):
    """A regular FAILED run does not trigger throttle cooldown."""
    from cogtainer.lambdas.dispatcher.handler import _is_throttle_cooldown_active

    repo = _repo(tmp_path)
    proc = _daemon("scheduler", status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    run = Run(
        process=proc.id,
        status=RunStatus.FAILED,
        error="Some other error",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        completed_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    repo.create_run(run)

    assert _is_throttle_cooldown_active(repo) is False

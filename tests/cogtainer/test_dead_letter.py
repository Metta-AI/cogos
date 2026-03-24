"""Tests for the dead-letter queue mechanism in the dispatcher."""

from datetime import UTC, datetime
from uuid import uuid4

from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import (
    Channel,
    ChannelType,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)


def _repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(str(tmp_path))


def test_flush_dead_letters_writes_failed_runs(tmp_path):
    """Failed runs are written to the dead-letter channel."""
    from cogtainer.lambdas.dispatcher.handler import _flush_dead_letters

    repo = _repo(tmp_path)

    process = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.FAILED, error="boom")
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.FAILED, error="boom")

    flushed = _flush_dead_letters(repo)
    assert flushed == 1

    dl_ch = repo.get_channel_by_name("system:dead-letter")
    assert dl_ch is not None
    msgs = repo.list_channel_messages(dl_ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["type"] == "executor:failed"
    assert msgs[0].payload["process_name"] == "worker"
    assert msgs[0].payload["error"] == "boom"


def test_flush_dead_letters_skips_already_reported(tmp_path):
    """Runs already reported are not duplicated."""
    from cogtainer.lambdas.dispatcher.handler import _flush_dead_letters

    repo = _repo(tmp_path)

    process = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.FAILED, error="boom")
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.FAILED, error="boom")

    # First flush
    assert _flush_dead_letters(repo) == 1
    # Second flush — should skip
    assert _flush_dead_letters(repo) == 0


def test_flush_dead_letters_tolerates_metadata_write_failure(tmp_path, monkeypatch):
    """Dead-letter flushing should not crash if run metadata cannot be persisted."""
    from cogtainer.lambdas.dispatcher.handler import _flush_dead_letters

    repo = _repo(tmp_path)

    process = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.FAILED, error="boom")
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.FAILED, error="boom")

    monkeypatch.setattr(
        repo,
        "update_run_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no metadata column")),
    )

    flushed = _flush_dead_letters(repo)
    assert flushed == 1

    dl_ch = repo.get_channel_by_name("system:dead-letter")
    assert dl_ch is not None
    msgs = repo.list_channel_messages(dl_ch.id, limit=10)
    assert len(msgs) == 1
    assert msgs[0].payload["type"] == "executor:failed"


def test_flush_dead_letters_ignores_completed_runs(tmp_path):
    """Completed runs are not flushed."""
    from cogtainer.lambdas.dispatcher.handler import _flush_dead_letters

    repo = _repo(tmp_path)

    process = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(process)

    run = Run(process=process.id, status=RunStatus.COMPLETED)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.COMPLETED)

    assert _flush_dead_letters(repo) == 0


def test_list_recent_failed_runs(tmp_path):
    """list_recent_failed_runs returns only failed/timeout runs."""
    repo = _repo(tmp_path)

    process = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.DISABLED)
    repo.upsert_process(process)

    r1 = Run(process=process.id, status=RunStatus.FAILED, error="e1")
    repo.create_run(r1)
    repo.complete_run(r1.id, status=RunStatus.FAILED, error="e1")

    r2 = Run(process=process.id, status=RunStatus.COMPLETED)
    repo.create_run(r2)
    repo.complete_run(r2.id, status=RunStatus.COMPLETED)

    r3 = Run(process=process.id, status=RunStatus.TIMEOUT, error="timeout")
    repo.create_run(r3)
    repo.complete_run(r3.id, status=RunStatus.TIMEOUT, error="timeout")

    failed = repo.list_recent_failed_runs(max_age_ms=60_000)
    statuses = {r.status for r in failed}
    assert RunStatus.COMPLETED not in statuses
    assert len(failed) == 2

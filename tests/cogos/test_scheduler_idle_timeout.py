"""Tests for scheduler idle timeout reaping (now a no-op)."""

from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus


def test_reap_is_noop(tmp_path):
    """reap_idle_processes is a no-op — daemons stay alive until killed."""
    repo = SqliteRepository(str(tmp_path))
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = Process(
        name="daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=[],
        idle_timeout_ms=1,  # would have been reaped instantly
    )
    repo.upsert_process(proc)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.WAITING

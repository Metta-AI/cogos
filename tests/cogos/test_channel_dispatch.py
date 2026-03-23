"""Tests for executor dispatch via the scheduler."""

from uuid import UUID

import pytest

from cogos.capabilities.scheduler import ExecutorDispatchResult, SchedulerCapability, SchedulerError
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Executor,
    ExecutorStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    RunStatus,
)


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path))


@pytest.fixture
def scheduler(repo):
    cap = SchedulerCapability.__new__(SchedulerCapability)
    cap.repo = repo
    return cap


def _make_process(repo, *, name="test-proc", status=ProcessStatus.RUNNABLE,
                  required_tags=None, metadata=None) -> Process:
    p = Process(
        name=name,
        mode=ProcessMode.DAEMON,
        status=status,
        required_tags=required_tags or [],
        priority=50.0,
        metadata=metadata or {},
    )
    repo.upsert_process(p)
    return p


def _register_executor(repo, *, executor_id="exec-1", executor_tags=None,
                        dispatch_type="channel") -> Executor:
    e = Executor(
        executor_id=executor_id,
        executor_tags=executor_tags or ["claude-code", "git"],
        dispatch_type=dispatch_type,
    )
    repo.register_executor(e)
    return e


class TestDispatchToExecutor:
    def test_dispatch_success(self, repo, scheduler):
        proc = _make_process(repo)
        _register_executor(repo)

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, ExecutorDispatchResult)
        assert result.process_name == "test-proc"
        assert result.executor_id == "exec-1"

        # Process should be RUNNING
        updated = repo.get_process(proc.id)
        assert updated.status == ProcessStatus.RUNNING

        # Executor should be BUSY
        executor = repo.get_executor("exec-1")
        assert executor.status == ExecutorStatus.BUSY
        assert executor.current_run_id == UUID(result.run_id)

        # Run should exist
        runs = repo.list_runs(process_id=proc.id, limit=1)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.RUNNING

    def test_dispatch_no_executor_blocks_process(self, repo, scheduler):
        proc = _make_process(repo)

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, SchedulerError)
        assert "no available executor" in result.error

        updated = repo.get_process(proc.id)
        assert updated.status == ProcessStatus.BLOCKED

    def test_dispatch_not_runnable_rejected(self, repo, scheduler):
        proc = _make_process(repo, status=ProcessStatus.WAITING)
        _register_executor(repo)

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, SchedulerError)
        assert "expected runnable" in result.error

    def test_dispatch_nonexistent_process(self, repo, scheduler):
        result = scheduler.dispatch_to_executor(process_id="00000000-0000-0000-0000-000000000000")
        assert isinstance(result, SchedulerError)
        assert "not found" in result.error

    def test_dispatch_empty_process_id(self, repo, scheduler):
        result = scheduler.dispatch_to_executor(process_id="")
        assert isinstance(result, SchedulerError)

    def test_dispatch_with_tag_filter(self, repo, scheduler):
        """Process requires GPU — only GPU executor should be selected."""
        proc = _make_process(repo, required_tags=["claude-code", "gpu"])
        _register_executor(repo, executor_id="exec-cpu", executor_tags=["claude-code", "git"])
        _register_executor(repo, executor_id="exec-gpu", executor_tags=["claude-code", "git", "gpu"])

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, ExecutorDispatchResult)
        assert result.executor_id == "exec-gpu"

    def test_dispatch_with_unmet_tags_blocks(self, repo, scheduler):
        """No executor has required GPU tag."""
        proc = _make_process(repo, required_tags=["gpu"])
        _register_executor(repo, executor_tags=["claude-code", "git"])

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, SchedulerError)
        assert "no available executor" in result.error
        updated = repo.get_process(proc.id)
        assert updated.status == ProcessStatus.BLOCKED

    def test_dispatch_skips_busy_executors(self, repo, scheduler):
        proc = _make_process(repo)
        _register_executor(repo, executor_id="exec-busy")
        _register_executor(repo, executor_id="exec-idle")
        repo.update_executor_status("exec-busy", ExecutorStatus.BUSY)

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, ExecutorDispatchResult)
        assert result.executor_id == "exec-idle"

    def test_dispatch_with_pending_delivery(self, repo, scheduler):
        """Dispatch should consume pending deliveries."""
        proc = _make_process(repo)
        _register_executor(repo)

        ch = Channel(name="task:assigned", channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        repo.create_handler(Handler(process=proc.id, channel=ch.id, enabled=True))
        msg = ChannelMessage(channel=ch.id, payload={"topic": "test"})
        repo.append_channel_message(msg)

        scheduler.match_messages()

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, ExecutorDispatchResult)
        assert result.run_id

    def test_multiple_dispatches_use_different_executors(self, repo, scheduler):
        proc1 = _make_process(repo, name="proc-1")
        proc2 = _make_process(repo, name="proc-2")
        _register_executor(repo, executor_id="exec-1")
        _register_executor(repo, executor_id="exec-2")

        r1 = scheduler.dispatch_to_executor(process_id=str(proc1.id))
        r2 = scheduler.dispatch_to_executor(process_id=str(proc2.id))

        assert isinstance(r1, ExecutorDispatchResult)
        assert isinstance(r2, ExecutorDispatchResult)
        assert r1.executor_id != r2.executor_id

    def test_lambda_pool_dispatch(self, repo, scheduler):
        """Lambda pool executor stays idle after dispatch (fire-and-forget)."""
        proc = _make_process(repo, required_tags=["lambda"])
        _register_executor(repo, executor_id="lambda-pool",
                          executor_tags=["lambda", "python"],
                          dispatch_type="lambda")

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))

        assert isinstance(result, ExecutorDispatchResult)
        assert result.executor_id == "lambda-pool"
        assert result.dispatch_type == "lambda"

        # Lambda pool should remain IDLE
        executor = repo.get_executor("lambda-pool")
        assert executor.status == ExecutorStatus.IDLE

    def test_no_tags_matches_any_executor(self, repo, scheduler):
        """Process with no required_tags matches any executor."""
        proc = _make_process(repo, required_tags=[])
        _register_executor(repo)

        result = scheduler.dispatch_to_executor(process_id=str(proc.id))
        assert isinstance(result, ExecutorDispatchResult)


class TestReapStaleExecutors:
    def test_reap_via_scheduler(self, repo, scheduler):
        _register_executor(repo, executor_id="exec-old")
        from datetime import timedelta
        e = repo.get_executor("exec-old")
        e.last_heartbeat_at = e.last_heartbeat_at - timedelta(seconds=600)

        count = scheduler.reap_stale_executors(heartbeat_interval_s=30)
        assert count == 1
        assert repo.get_executor("exec-old").status == ExecutorStatus.DEAD

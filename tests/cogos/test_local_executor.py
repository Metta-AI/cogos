"""Tests for cogos.runtime.local – run_and_complete and run_local_tick."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.runtime.local import run_and_complete, run_local_tick


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


# ---- run_local_tick tests ----


def test_run_local_tick_executes_runnable_process(tmp_path):
    """ONE_SHOT process with RUNNABLE status is executed and completed."""
    repo = _repo(tmp_path)
    p = Process(
        name="tick-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE,
        runner="local",
    )
    repo.upsert_process(p)

    executed = run_local_tick(repo, None, execute_fn=_noop_execute)

    assert executed == 1
    assert repo.get_process(p.id).status == ProcessStatus.COMPLETED


def test_run_local_tick_no_work(tmp_path):
    """Empty repo -> run_local_tick returns 0."""
    repo = _repo(tmp_path)

    executed = run_local_tick(repo, None, execute_fn=_noop_execute)

    assert executed == 0


def test_run_local_tick_matches_channel_messages(tmp_path):
    """DAEMON process in WAITING gets executed after channel message delivery."""
    repo = _repo(tmp_path)
    p = Process(
        name="daemon-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="local",
    )
    repo.upsert_process(p)

    ch = Channel(
        name="test-channel",
        owner_process=p.id,
        channel_type=ChannelType.NAMED,
    )
    repo.upsert_channel(ch)

    handler = Handler(
        process=p.id,
        channel=ch.id,
        enabled=True,
    )
    repo.create_handler(handler)

    msg = ChannelMessage(
        channel=ch.id,
        sender_process=p.id,
        payload={"hello": "world"},
    )
    repo.append_channel_message(msg)

    executed = run_local_tick(repo, None, execute_fn=_noop_execute)

    assert executed == 1
    assert repo.get_process(p.id).status == ProcessStatus.WAITING

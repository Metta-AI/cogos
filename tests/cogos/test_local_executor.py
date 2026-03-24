"""Tests for cogos.runtime.local – run_and_complete and run_local_tick."""

from datetime import datetime, timezone

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
        required_tags=["local"],
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


def _process(name: str, *, mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING) -> Process:
    return Process(name=name, mode=mode, status=status, required_tags=["local"])


# ---- Tests ----


def test_run_and_complete_success(tmp_path):
    """One-shot process, execute succeeds -> run COMPLETED, process COMPLETED."""
    repo = _repo(tmp_path)
    process = _make_process(repo)
    run = _make_run(repo, process)

    result = run_and_complete(
        process,
        {},
        run,
        None,
        repo,
        execute_fn=_noop_execute,
    )

    assert result.id == run.id
    _tmp_get_run = repo.get_run(run.id)
    assert _tmp_get_run is not None
    assert _tmp_get_run.status == RunStatus.COMPLETED
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.COMPLETED


def test_run_and_complete_daemon_goes_to_waiting(tmp_path):
    """Daemon process, no pending deliveries -> process goes to WAITING after success."""
    repo = _repo(tmp_path)
    process = _make_process(repo, mode=ProcessMode.DAEMON)
    run = _make_run(repo, process)

    result = run_and_complete(
        process,
        {},
        run,
        None,
        repo,
        execute_fn=_noop_execute,
    )

    _tmp_get_run = repo.get_run(run.id)
    assert _tmp_get_run is not None
    assert _tmp_get_run.status == RunStatus.COMPLETED
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.WAITING


def test_run_and_complete_failure_disables_one_shot(tmp_path):
    """One-shot with max_retries=0, execute raises -> run FAILED, process DISABLED."""
    repo = _repo(tmp_path)
    process = _make_process(repo, max_retries=0)
    run = _make_run(repo, process)

    run_and_complete(
        process,
        {},
        run,
        None,
        repo,
        execute_fn=_failing_execute,
    )

    _tmp_get_run = repo.get_run(run.id)
    assert _tmp_get_run is not None
    assert _tmp_get_run.status == RunStatus.FAILED
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.DISABLED


def test_run_and_complete_returns_run_on_failure(tmp_path):
    """One-shot with max_retries=1, execute raises -> process RUNNABLE, run returned."""
    repo = _repo(tmp_path)
    process = _make_process(repo, max_retries=1)
    run = _make_run(repo, process)

    result = run_and_complete(
        process,
        {},
        run,
        None,
        repo,
        execute_fn=_failing_execute,
    )

    assert result.id == run.id
    _tmp_get_run = repo.get_run(run.id)
    assert _tmp_get_run is not None
    assert _tmp_get_run.status == RunStatus.FAILED
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE


def test_local_repository_merges_stale_writers(tmp_path):
    repo1 = _repo(tmp_path)
    repo2 = _repo(tmp_path)

    repo1.upsert_process(_process("p1", status=ProcessStatus.RUNNABLE))
    repo2.upsert_process(_process("p2", status=ProcessStatus.RUNNABLE))

    names = [process.name for process in _repo(tmp_path).list_processes()]
    assert names == ["p1", "p2"]


def test_run_and_complete_respects_out_of_band_disable(tmp_path):
    repo = _repo(tmp_path)
    process = _make_process(repo)
    run = _make_run(repo, process)

    def _disable_mid_run(process, event_data, run, config, repo, **kwargs):
        repo.update_process_status(process.id, ProcessStatus.DISABLED)
        return run

    run_and_complete(
        process,
        {},
        run,
        None,
        repo,
        execute_fn=_disable_mid_run,
    )

    _tmp_get_run = repo.get_run(run.id)
    assert _tmp_get_run is not None
    assert _tmp_get_run.status == RunStatus.COMPLETED
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.DISABLED


# ---- run_local_tick tests ----


def test_run_local_tick_executes_runnable_process(tmp_path):
    """ONE_SHOT process with RUNNABLE status is executed and completed."""
    repo = _repo(tmp_path)
    p = Process(
        name="tick-proc",
        mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE,
        required_tags=["local"],
    )
    repo.upsert_process(p)

    executed = run_local_tick(repo, None, execute_fn=_noop_execute)

    assert executed == 1
    _tmp_get_process = repo.get_process(p.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.COMPLETED


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
        required_tags=["local"],
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
    _tmp_get_process = repo.get_process(p.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.WAITING


def test_run_local_tick_uses_prod_dispatch_envelope(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="daemon-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    channel = Channel(name="test-channel", channel_type=ChannelType.NAMED)
    repo.upsert_channel(channel)
    channel = repo.get_channel_by_name("test-channel")
    assert channel is not None

    repo.create_handler(Handler(process=process.id, channel=channel.id, enabled=True))
    message = ChannelMessage(
        channel=channel.id,
        sender_process=process.id,
        payload={"hello": "world"},
    )
    repo.append_channel_message(message)

    captured = {}

    def _capture_execute(process, event_data, run, config, repo, **kwargs):
        captured.update(event_data)
        return run

    executed = run_local_tick(repo, None, execute_fn=_capture_execute)

    assert executed == 1
    assert captured["process_id"] == str(process.id)
    assert captured["run_id"]
    assert captured["message_id"] == str(message.id)
    assert captured["payload"] == {"hello": "world"}


def test_run_local_tick_applies_system_ticks(tmp_path):
    repo = _repo(tmp_path)
    process = Process(
        name="hourly-daemon",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=["local"],
    )
    repo.upsert_process(process)

    channel = Channel(name="system:tick:hour", channel_type=ChannelType.NAMED)
    repo.upsert_channel(channel)
    channel = repo.get_channel_by_name("system:tick:hour")
    assert channel is not None
    repo.create_handler(Handler(process=process.id, channel=channel.id, enabled=True))

    executed = run_local_tick(
        repo,
        None,
        execute_fn=_noop_execute,
        now=datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert executed == 1
    _tmp_get_process = repo.get_process(process.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.WAITING

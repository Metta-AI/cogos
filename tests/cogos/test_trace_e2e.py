"""End-to-end test: trace_id flows from message through dispatch to run."""

from __future__ import annotations

import tempfile
from uuid import uuid4

from cogos.capabilities.scheduler import SchedulerCapability, SchedulerError
from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)
from cogos.runtime.dispatch import build_dispatch_event


def _fresh_repo():
    return SqliteRepository(data_dir=tempfile.mkdtemp())


def _setup_repo_with_traced_message():
    """Create a repo with a process, handler, channel, and a traced message."""
    repo = _fresh_repo()

    proc = Process(
        name="test-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=[],
    )
    repo.upsert_process(proc)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    trace_id = uuid4()
    msg_id = repo.append_channel_message(
        ChannelMessage(
            channel=ch.id,
            payload={"content": "hello", "message_type": "discord:dm"},
            trace_id=trace_id,
            trace_meta={
                "discord_created_at_ms": 1000,
                "bridge_received_at_ms": 1001,
                "db_written_at_ms": 1002,
            },
        )
    )

    return repo, proc, trace_id, msg_id


def test_trace_id_flows_from_message_to_delivery():
    """Delivery auto-created by append_channel_message should inherit trace_id."""
    repo, proc, trace_id, _ = _setup_repo_with_traced_message()

    deliveries = repo.get_pending_deliveries(proc.id)
    assert deliveries is not None
    assert len(deliveries) == 1
    assert deliveries[0].trace_id == trace_id


def test_trace_id_flows_from_dispatch_to_run():
    """dispatch_process should copy trace_id from delivery to run."""
    repo, proc, trace_id, _ = _setup_repo_with_traced_message()

    proc = repo.get_process(proc.id)
    assert proc is not None
    assert proc.status == ProcessStatus.RUNNABLE

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))
    assert not isinstance(result, SchedulerError), f"dispatch failed: {result}"
    assert result.trace_id == str(trace_id)

    from uuid import UUID

    run = repo.get_run(UUID(result.run_id))
    assert run is not None
    assert run.trace_id == trace_id


def test_build_dispatch_event_includes_trace_id():
    """build_dispatch_event should include trace_id and dispatched_at_ms."""
    repo, proc, trace_id, _ = _setup_repo_with_traced_message()

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))

    event = build_dispatch_event(repo, result)
    assert event["trace_id"] == str(trace_id)
    assert "dispatched_at_ms" in event
    assert isinstance(event["dispatched_at_ms"], int)


def test_message_without_trace_id_works():
    """Non-traced messages should still work normally."""
    repo = _fresh_repo()

    proc = Process(
        name="untraced-proc",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=[],
    )
    repo.upsert_process(proc)

    ch = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    repo.append_channel_message(
        ChannelMessage(
            channel=ch.id,
            payload={"content": "regular message"},
        )
    )

    deliveries = repo.get_pending_deliveries(proc.id)
    assert deliveries is not None
    assert len(deliveries) == 1
    assert deliveries[0].trace_id is None

    scheduler = SchedulerCapability(repo, uuid4())
    result = scheduler.dispatch_process(process_id=str(proc.id))
    assert not isinstance(result, SchedulerError), f"dispatch failed: {result}"
    assert result.trace_id is None

    event = build_dispatch_event(repo, result)
    assert event["trace_id"] is None

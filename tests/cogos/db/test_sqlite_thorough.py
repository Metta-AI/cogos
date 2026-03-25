"""Thorough tests for SqliteRepository covering edge cases beyond test_sqlite_repository.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from cogos.db.models import (
    ALL_EPOCHS,
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    CogosOperation,
    Cron,
    Delivery,
    Executor,
    ExecutorStatus,
    ExecutorToken,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    Run,
    RunStatus,
    Schema,
    Span,
    SpanEvent,
    SpanStatus,
)
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.db.models.trace import RequestTrace, Trace
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType
from cogos.db.sqlite_repository import SqliteRepository


@pytest.fixture
def repo(tmp_path: Path) -> SqliteRepository:
    return SqliteRepository(str(tmp_path))


@pytest.fixture
def repo_with_process(repo: SqliteRepository) -> tuple[SqliteRepository, Process]:
    p = Process(name="worker", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    return repo, p


# ── Protocol compliance ──────────────────────────────────────

def test_implements_protocol(repo: SqliteRepository) -> None:
    from cogos.db.protocol import CogosRepositoryInterface
    assert isinstance(repo, CogosRepositoryInterface)


# ── Batch / Transaction ─────────────────────────────────────

def test_nested_batch_commits_only_on_outer(repo: SqliteRepository) -> None:
    with repo.batch():
        repo.set_meta("a", "1")
        with repo.batch():
            repo.set_meta("b", "2")
        # inner batch done but outer not yet committed
    assert repo.get_meta("a") == {"key": "a", "value": "1"}
    assert repo.get_meta("b") == {"key": "b", "value": "2"}


def test_batch_rollback_on_exception(repo: SqliteRepository) -> None:
    repo.set_meta("before", "exists")
    with pytest.raises(ValueError):
        with repo.batch():
            repo.set_meta("inside", "val")
            raise ValueError("oops")
    assert repo.get_meta("before") is not None
    assert repo.get_meta("inside") is None


def test_batch_depth_reset_after_exception(repo: SqliteRepository) -> None:
    with pytest.raises(RuntimeError):
        with repo.batch():
            raise RuntimeError("fail")
    assert repo._batch_depth == 0
    # Should work normally after
    repo.set_meta("after", "ok")
    assert repo.get_meta("after") is not None


# ── Process edge cases ───────────────────────────────────────

def test_upsert_process_idempotent_by_name(repo: SqliteRepository) -> None:
    p1 = Process(name="worker", mode=ProcessMode.ONE_SHOT, content="v1")
    id1 = repo.upsert_process(p1)
    p2 = Process(name="worker", mode=ProcessMode.ONE_SHOT, content="v2")
    id2 = repo.upsert_process(p2)
    assert id1 == id2
    got = repo.get_process_by_name("worker")
    assert got is not None
    assert got.content == "v2"


def test_list_processes_all_epochs(repo: SqliteRepository) -> None:
    p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, epoch=0)
    repo.upsert_process(p1)
    repo.increment_epoch()
    p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, epoch=1)
    repo.upsert_process(p2)
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    assert len(all_procs) == 2


def test_try_transition_process_wrong_status(repo: SqliteRepository) -> None:
    p = Process(name="x", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    result = repo.try_transition_process(p.id, ProcessStatus.RUNNABLE, ProcessStatus.DISABLED)
    assert result is False
    got = repo.get_process(p.id)
    assert got is not None
    assert got.status == ProcessStatus.WAITING


def test_update_process_status_runnable_preserves_runnable_since(repo: SqliteRepository) -> None:
    p = Process(name="x", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
    got1 = repo.get_process(p.id)
    assert got1 is not None
    assert got1.runnable_since is not None
    first_runnable_since = got1.runnable_since

    repo.update_process_status(p.id, ProcessStatus.RUNNABLE)
    got2 = repo.get_process(p.id)
    assert got2 is not None
    assert got2.runnable_since == first_runnable_since


def test_cascade_disable_children(repo: SqliteRepository) -> None:
    parent = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, parent_process=parent.id)
    repo.upsert_process(child)
    grandchild = Process(
        name="grandchild", mode=ProcessMode.ONE_SHOT,
        status=ProcessStatus.RUNNABLE, parent_process=child.id,
    )
    repo.upsert_process(grandchild)

    repo.update_process_status(parent.id, ProcessStatus.DISABLED)
    assert repo.get_process(child.id).status == ProcessStatus.DISABLED  # type: ignore[union-attr]
    assert repo.get_process(grandchild.id).status == ProcessStatus.DISABLED  # type: ignore[union-attr]


def test_get_runnable_processes_ordered_by_priority(repo: SqliteRepository) -> None:
    low = Process(name="low", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, priority=1.0)
    high = Process(name="high", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNABLE, priority=10.0)
    repo.upsert_process(low)
    repo.upsert_process(high)
    repo.update_process_status(low.id, ProcessStatus.RUNNABLE)
    repo.update_process_status(high.id, ProcessStatus.RUNNABLE)
    procs = repo.get_runnable_processes()
    assert procs[0].name == "high"


def test_delete_process(repo: SqliteRepository) -> None:
    p = Process(name="deleteme", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    assert repo.delete_process(p.id)
    assert repo.get_process(p.id) is None


def test_increment_retry(repo: SqliteRepository) -> None:
    p = Process(name="retry", mode=ProcessMode.ONE_SHOT, max_retries=3)
    repo.upsert_process(p)
    assert repo.increment_retry(p.id)
    got = repo.get_process(p.id)
    assert got is not None
    assert got.retry_count == 1


# ── Process JSON fields round-trip ───────────────────────────

def test_process_all_json_fields(repo: SqliteRepository) -> None:
    p = Process(
        name="full",
        mode=ProcessMode.DAEMON,
        content="prompt",
        priority=5.5,
        resources=[uuid4()],
        required_tags=["nvidia"],
        metadata={"key": "val", "nested": {"a": 1}},
        output_events=["done"],
        model_constraints={"max_tokens": 100},
        return_schema={"type": "object"},
        model="claude-3",
        preemptible=True,
        tty=True,
        clear_context=True,
        idle_timeout_ms=5000,
        max_duration_ms=30000,
        max_retries=2,
        retry_backoff_ms=1000,
        executor="lambda",
    )
    repo.upsert_process(p)
    got = repo.get_process(p.id)
    assert got is not None
    assert len(got.resources) == 1
    assert got.required_tags == ["nvidia"]
    assert got.metadata == {"key": "val", "nested": {"a": 1}}
    assert got.output_events == ["done"]
    assert got.model_constraints == {"max_tokens": 100}
    assert got.return_schema == {"type": "object"}
    assert got.model == "claude-3"
    assert got.preemptible is True
    assert got.tty is True
    assert got.clear_context is True
    assert got.idle_timeout_ms == 5000
    assert got.max_duration_ms == 30000
    assert got.max_retries == 2
    assert got.retry_backoff_ms == 1000
    assert got.executor == "lambda"
    assert got.mode == ProcessMode.DAEMON
    assert got.priority == 5.5


# ── Files ────────────────────────────────────────────────────

def test_bulk_upsert_files(repo: SqliteRepository) -> None:
    files = [
        ("a.txt", "content-a", "image", []),
        ("b.txt", "content-b", "image", ["a.txt"]),
    ]
    count = repo.bulk_upsert_files(files)
    assert count == 2
    fa = repo.get_file_by_key("a.txt")
    assert fa is not None
    fv = repo.get_active_file_version(fa.id)
    assert fv is not None
    assert fv.content == "content-a"


def test_bulk_upsert_files_updates_existing(repo: SqliteRepository) -> None:
    repo.bulk_upsert_files([("a.txt", "v1", "image", [])])
    repo.bulk_upsert_files([("a.txt", "v2", "image", ["inc"])])
    fa = repo.get_file_by_key("a.txt")
    assert fa is not None
    assert fa.includes == ["inc"]
    fv = repo.get_active_file_version(fa.id)
    assert fv is not None
    assert fv.content == "v2"
    assert fv.version == 2


def test_glob_files(repo: SqliteRepository) -> None:
    for key in ["src/a.py", "src/b.py", "tests/c.py"]:
        f = File(key=key)
        repo.insert_file(f)
        repo.insert_file_version(FileVersion(file_id=f.id, version=1, content="x"))
    matches = repo.glob_files("src/*.py")
    assert set(matches) == {"src/a.py", "src/b.py"}


def test_delete_files_by_prefixes(repo: SqliteRepository) -> None:
    for key in ["apps/a.py", "apps/b.py", "core/c.py"]:
        f = File(key=key)
        repo.insert_file(f)
    deleted = repo.delete_files_by_prefixes(["apps/"])
    assert deleted == 2
    assert repo.get_file_by_key("core/c.py") is not None


def test_file_version_set_active(repo: SqliteRepository) -> None:
    f = File(key="test.txt")
    repo.insert_file(f)
    fv1 = FileVersion(file_id=f.id, version=1, content="v1", is_active=True)
    repo.insert_file_version(fv1)
    fv2 = FileVersion(file_id=f.id, version=2, content="v2", is_active=True)
    repo.insert_file_version(fv2)
    active = repo.get_active_file_version(f.id)
    assert active is not None
    assert active.version == 2

    repo.set_active_file_version(f.id, 1)
    active = repo.get_active_file_version(f.id)
    assert active is not None
    assert active.version == 1


def test_update_file_version_content(repo: SqliteRepository) -> None:
    f = File(key="test.txt")
    repo.insert_file(f)
    fv = FileVersion(file_id=f.id, version=1, content="old")
    repo.insert_file_version(fv)
    assert repo.update_file_version_content(f.id, 1, "new")
    active = repo.get_active_file_version(f.id)
    assert active is not None
    assert active.content == "new"


def test_delete_file_version(repo: SqliteRepository) -> None:
    f = File(key="test.txt")
    repo.insert_file(f)
    fv = FileVersion(file_id=f.id, version=1, content="x")
    repo.insert_file_version(fv)
    assert repo.delete_file_version(f.id, 1)
    assert repo.get_active_file_version(f.id) is None


# ── Capabilities ─────────────────────────────────────────────

def test_capability_crud(repo: SqliteRepository) -> None:
    cap = Capability(
        name="send_email",
        description="Send emails",
        handler="email_handler",
        schema={"type": "object"},
        metadata={"tier": "premium"},
    )
    repo.upsert_capability(cap)
    got = repo.get_capability(cap.id)
    assert got is not None
    assert got.name == "send_email"
    assert got.schema == {"type": "object"}

    by_name = repo.get_capability_by_name("send_email")
    assert by_name is not None

    by_handler = repo.get_capability_by_handler("email_handler")
    assert by_handler is not None

    caps = repo.list_capabilities()
    assert len(caps) == 1

    caps_enabled = repo.list_capabilities(enabled_only=True)
    assert len(caps_enabled) == 1


def test_search_capabilities(repo: SqliteRepository) -> None:
    cap1 = Capability(name="email", description="send email")
    cap2 = Capability(name="slack", description="post to slack")
    repo.upsert_capability(cap1)
    repo.upsert_capability(cap2)
    results = repo.search_capabilities("email")
    assert len(results) == 1
    assert results[0].name == "email"


def test_search_capabilities_scoped_to_process(repo: SqliteRepository) -> None:
    cap1 = Capability(name="email", description="send email")
    cap2 = Capability(name="slack", description="post to slack")
    repo.upsert_capability(cap1)
    repo.upsert_capability(cap2)

    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    repo.create_process_capability(ProcessCapability(process=p.id, capability=cap1.id, name="email"))

    results = repo.search_capabilities("", process_id=p.id)
    assert len(results) == 1
    assert results[0].name == "email"


# ── Handlers ─────────────────────────────────────────────────

def test_handler_idempotent_on_same_channel(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    h1 = Handler(process=p.id, channel=ch.id)
    id1 = repo.create_handler(h1)
    h2 = Handler(process=p.id, channel=ch.id)
    id2 = repo.create_handler(h2)
    assert id1 == id2

    handlers = repo.list_handlers()
    assert len(handlers) == 1


def test_match_handlers_returns_empty(repo: SqliteRepository) -> None:
    assert repo.match_handlers("some.event") == []


# ── Deliveries ───────────────────────────────────────────────

def test_delivery_lifecycle(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    msg = ChannelMessage(channel=ch.id, payload={"text": "hello"})
    repo.append_channel_message(msg)

    deliveries = repo.get_pending_deliveries(p.id)
    assert len(deliveries) == 1
    assert repo.has_pending_deliveries(p.id)

    run = Run(process=p.id, message=msg.id)
    repo.create_run(run)
    repo.mark_queued(deliveries[0].id, run.id)

    pending_after_queue = repo.get_pending_deliveries(p.id)
    assert len(pending_after_queue) == 0

    repo.requeue_delivery(deliveries[0].id)
    assert repo.has_pending_deliveries(p.id)

    repo.mark_delivered(deliveries[0].id, run.id)
    assert not repo.has_pending_deliveries(p.id)


def test_delivery_idempotent(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    d = Delivery(message=uuid4(), handler=h.id)
    id1, created1 = repo.create_delivery(d)
    id2, created2 = repo.create_delivery(d)
    assert id1 == id2
    assert created1 is True
    assert created2 is False


def test_list_deliveries_filters(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    msg_id = uuid4()
    d = Delivery(message=msg_id, handler=h.id)
    repo.create_delivery(d)

    by_msg = repo.list_deliveries(message_id=msg_id)
    assert len(by_msg) == 1

    by_handler = repo.list_deliveries(handler_id=h.id)
    assert len(by_handler) == 1

    all_epochs = repo.list_deliveries(epoch=ALL_EPOCHS)
    assert len(all_epochs) == 1


def test_mark_run_deliveries_delivered(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    run = Run(process=p.id)
    repo.create_run(run)

    d1 = Delivery(message=uuid4(), handler=h.id)
    repo.create_delivery(d1)
    repo.mark_queued(d1.id, run.id)

    count = repo.mark_run_deliveries_delivered(run.id)
    assert count == 1


def test_rollback_dispatch(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)

    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    _d = Delivery(message=uuid4(), handler=uuid4())
    # We can't create this delivery through create_delivery because handler doesn't exist
    # Test rollback_dispatch with delivery_id=None
    repo.rollback_dispatch(p.id, run.id, delivery_id=None, error="test error")

    completed_run = repo.get_run(run.id)
    assert completed_run is not None
    assert completed_run.status == RunStatus.FAILED
    assert completed_run.error == "test error"

    got_proc = repo.get_process(p.id)
    assert got_proc is not None
    assert got_proc.status == ProcessStatus.RUNNABLE


def test_get_latest_delivery_time(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    msg = ChannelMessage(channel=ch.id, payload={"text": "hi"})
    repo.append_channel_message(msg)

    latest = repo.get_latest_delivery_time(h.id)
    assert latest is not None


# ── Runs ─────────────────────────────────────────────────────

def test_run_complete_with_all_fields(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)

    run = Run(process=p.id)
    repo.create_run(run)

    repo.complete_run(
        run.id,
        status=RunStatus.COMPLETED,
        tokens_in=100,
        tokens_out=200,
        cost_usd=Decimal("0.05"),
        duration_ms=1500,
        model_version="claude-3",
        result={"output": "hello"},
        snapshot={"state": "final"},
        scope_log=[{"event": "done"}],
    )

    got = repo.get_run(run.id)
    assert got is not None
    assert got.status == RunStatus.COMPLETED
    assert got.tokens_in == 100
    assert got.tokens_out == 200
    assert got.cost_usd == Decimal("0.05")
    assert got.duration_ms == 1500
    assert got.model_version == "claude-3"
    assert got.result == {"output": "hello"}
    assert got.snapshot == {"state": "final"}
    assert got.scope_log == [{"event": "done"}]
    assert got.completed_at is not None


def test_timeout_stale_runs(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)

    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    # Backdating created_at to make it stale
    repo._execute(
        "UPDATE cogos_run SET created_at = :old WHERE id = :id",
        {"old": (datetime.now(UTC) - timedelta(hours=1)).isoformat(), "id": str(run.id)},
    )

    count = repo.timeout_stale_runs(max_age_ms=60_000)
    assert count == 1
    got = repo.get_run(run.id)
    assert got is not None
    assert got.status == RunStatus.TIMEOUT


def test_list_recent_failed_runs(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)

    run = Run(process=p.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.FAILED, error="boom")

    failed = repo.list_recent_failed_runs()
    assert len(failed) == 1
    assert failed[0].error == "boom"


def test_update_run_metadata(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)

    run = Run(process=p.id, metadata={"a": 1})
    repo.create_run(run)
    repo.update_run_metadata(run.id, {"b": 2})

    got = repo.get_run(run.id)
    assert got is not None
    assert got.metadata == {"a": 1, "b": 2}


def test_list_runs_with_filters(repo: SqliteRepository) -> None:
    p1 = Process(name="w1", mode=ProcessMode.ONE_SHOT)
    p2 = Process(name="w2", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p1)
    repo.upsert_process(p2)

    r1 = Run(process=p1.id, status=RunStatus.RUNNING)
    r2 = Run(process=p2.id, status=RunStatus.RUNNING)
    repo.create_run(r1)
    repo.create_run(r2)
    repo.complete_run(r1.id, status=RunStatus.COMPLETED)

    by_pid = repo.list_runs(process_id=p1.id)
    assert len(by_pid) == 1

    by_pids = repo.list_runs(process_ids=[p1.id, p2.id])
    assert len(by_pids) == 2

    by_status = repo.list_runs(status="running")
    assert len(by_status) == 1
    assert by_status[0].process == p2.id


def test_list_runs_slim(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    run = Run(process=p.id)
    repo.create_run(run)
    repo.complete_run(run.id, status=RunStatus.COMPLETED, result={"big": "data"}, snapshot={"more": "data"})

    slim = repo.list_runs(slim=True)
    assert len(slim) == 1
    assert slim[0].result is None
    assert slim[0].snapshot is None


def test_list_runs_by_process_glob(repo: SqliteRepository) -> None:
    for name in ["worker.a", "worker.b", "init"]:
        p = Process(name=name, mode=ProcessMode.ONE_SHOT)
        repo.upsert_process(p)
        repo.create_run(Run(process=p.id))

    runs = repo.list_runs_by_process_glob("worker.*")
    assert len(runs) == 2


def test_list_file_mutations(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    run = Run(process=p.id)
    repo.create_run(run)

    f = File(key="test.txt")
    repo.insert_file(f)
    fv = FileVersion(file_id=f.id, version=1, content="x", run_id=run.id)
    repo.insert_file_version(fv)

    mutations = repo.list_file_mutations(run.id)
    assert len(mutations) == 1
    assert mutations[0]["key"] == "test.txt"


# ── Traces & Spans ───────────────────────────────────────────

def test_trace_crud(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    run = Run(process=p.id)
    repo.create_run(run)

    trace = Trace(run=run.id, capability_calls=[{"name": "email"}], file_ops=[{"op": "write"}])
    tid = repo.create_trace(trace)
    assert tid == trace.id


def test_request_trace_and_spans(repo: SqliteRepository) -> None:
    rt = RequestTrace(cogent_id="dr.gamma", source="discord", source_ref="msg-123")
    repo.create_request_trace(rt)
    got = repo.get_request_trace(rt.id)
    assert got is not None
    assert got.cogent_id == "dr.gamma"

    span = Span(trace_id=rt.id, name="handle_message")
    repo.create_span(span)
    spans = repo.list_spans(rt.id)
    assert len(spans) == 1
    assert spans[0].status == SpanStatus.RUNNING

    repo.complete_span(span.id, status="completed", metadata={"tokens": 42})
    spans = repo.list_spans(rt.id)
    assert spans[0].status == SpanStatus.COMPLETED
    assert spans[0].metadata == {"tokens": 42}

    event = SpanEvent(span_id=span.id, event="tool_call", message="called email")
    repo.create_span_event(event)
    events = repo.list_span_events(span.id)
    assert len(events) == 1

    trace_events = repo.list_span_events_for_trace(rt.id)
    assert len(trace_events) == 1


def test_complete_span_merges_metadata(repo: SqliteRepository) -> None:
    rt = RequestTrace(cogent_id="x", source="test")
    repo.create_request_trace(rt)
    span = Span(trace_id=rt.id, name="s", metadata={"a": 1})
    repo.create_span(span)
    repo.complete_span(span.id, metadata={"b": 2})
    got = repo.list_spans(rt.id)[0]
    assert got.metadata == {"a": 1, "b": 2}


# ── Channels ─────────────────────────────────────────────────

def test_channel_close(repo: SqliteRepository) -> None:
    ch = Channel(name="temp", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    assert repo.close_channel(ch.id)
    got = repo.get_channel(ch.id)
    assert got is not None
    assert got.closed_at is not None


def test_list_channels_by_owner(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    ch1 = Channel(name="owned", channel_type=ChannelType.NAMED, owner_process=p.id)
    ch2 = Channel(name="unowned", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch1)
    repo.upsert_channel(ch2)

    owned = repo.list_channels(owner_process=p.id)
    assert len(owned) == 1
    assert owned[0].name == "owned"


def test_channel_message_idempotency(repo: SqliteRepository) -> None:
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    msg1 = ChannelMessage(channel=ch.id, payload={"n": 1}, idempotency_key="key-1")
    id1 = repo.append_channel_message(msg1)
    msg2 = ChannelMessage(channel=ch.id, payload={"n": 2}, idempotency_key="key-1")
    id2 = repo.append_channel_message(msg2)
    assert id1 == id2

    messages = repo.list_channel_messages(ch.id)
    assert len(messages) == 1


def test_list_channel_messages_since(repo: SqliteRepository) -> None:
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    now = datetime.now(UTC)
    msg = ChannelMessage(channel=ch.id, payload={"n": 1})
    repo.append_channel_message(msg)

    old = now - timedelta(hours=1)
    messages = repo.list_channel_messages(ch.id, since=old)
    assert len(messages) == 1

    future = now + timedelta(hours=1)
    messages = repo.list_channel_messages(ch.id, since=future)
    assert len(messages) == 0


# ── Wait Conditions ──────────────────────────────────────────

def test_wait_condition_lifecycle(repo: SqliteRepository) -> None:
    p = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)

    child1 = Process(name="child1", mode=ProcessMode.ONE_SHOT, parent_process=p.id)
    child2 = Process(name="child2", mode=ProcessMode.ONE_SHOT, parent_process=p.id)
    repo.upsert_process(child1)
    repo.upsert_process(child2)

    wc = WaitCondition(
        process=p.id,
        type=WaitConditionType.WAIT_ALL,
        pending=[str(child1.id), str(child2.id)],
    )
    repo.create_wait_condition(wc)

    got = repo.get_pending_wait_condition_for_process(p.id)
    assert got is not None
    assert len(got.pending) == 2

    remaining = repo.remove_from_pending(wc.id, str(child1.id))
    assert len(remaining) == 1

    remaining = repo.remove_from_pending(wc.id, str(child2.id))
    assert len(remaining) == 0

    repo.resolve_wait_condition(wc.id)
    got = repo.get_pending_wait_condition_for_process(p.id)
    assert got is None


# ── Cron Rules ───────────────────────────────────────────────

def test_cron_crud(repo: SqliteRepository) -> None:
    c = Cron(expression="*/5 * * * *", channel_name="heartbeat", payload={"type": "tick"})
    repo.upsert_cron(c)

    rules = repo.list_cron_rules()
    assert len(rules) == 1
    assert rules[0].expression == "*/5 * * * *"

    repo.update_cron_enabled(c.id, False)
    enabled = repo.list_cron_rules(enabled_only=True)
    assert len(enabled) == 0

    assert repo.delete_cron(c.id)
    assert len(repo.list_cron_rules()) == 0


# ── Alerts ───────────────────────────────────────────────────

def test_alerts_lifecycle(repo: SqliteRepository) -> None:
    repo.create_alert("critical", "system", "monitor", "CPU 100%", {"host": "a"})
    repo.create_alert("warning", "info", "check", "OK")

    alerts = repo.list_alerts()
    assert len(alerts) == 2

    repo.resolve_alert(alerts[0].id)
    unresolved = repo.list_alerts(resolved=False)
    assert len(unresolved) == 1

    all_alerts = repo.list_alerts(resolved=True)
    assert len(all_alerts) == 2

    count = repo.resolve_all_alerts()
    assert count == 1  # only 1 was still unresolved

    repo.delete_alert(alerts[0].id)
    assert len(repo.list_alerts(resolved=True)) == 1


# ── Resources ────────────────────────────────────────────────

def test_resource_upsert(repo: SqliteRepository) -> None:
    r = Resource(name="gpu-pool", resource_type=ResourceType.POOL, capacity=4.0, metadata={"type": "A100"})
    repo.upsert_resource(r)
    resources = repo.list_resources()
    assert len(resources) == 1
    assert resources[0].capacity == 4.0
    assert resources[0].metadata == {"type": "A100"}


# ── Schemas ──────────────────────────────────────────────────

def test_schema_crud(repo: SqliteRepository) -> None:
    s = Schema(name="task_schema", definition={"type": "object", "properties": {"name": {"type": "string"}}})
    repo.upsert_schema(s)
    got = repo.get_schema(s.id)
    assert got is not None
    by_name = repo.get_schema_by_name("task_schema")
    assert by_name is not None
    schemas = repo.list_schemas()
    assert len(schemas) == 1


# ── Operations ───────────────────────────────────────────────

def test_operations(repo: SqliteRepository) -> None:
    op = CogosOperation(type="reboot", metadata={"reason": "update"})
    repo.add_operation(op)
    ops = repo.list_operations()
    assert len(ops) == 1
    assert ops[0].type == "reboot"


# ── Executors ────────────────────────────────────────────────

def test_executor_reap_stale(repo: SqliteRepository) -> None:
    e = Executor(executor_id="cc-1", channel_type="claude-code", executor_tags=["fast"])
    repo.register_executor(e)

    # Backdate heartbeat to make it stale/dead
    old_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    repo._execute(
        "UPDATE cogos_executor SET last_heartbeat_at = :t WHERE executor_id = :eid",
        {"t": old_time, "eid": "cc-1"},
    )
    dead_count = repo.reap_stale_executors(heartbeat_interval_s=30)
    assert dead_count == 1
    got = repo.get_executor("cc-1")
    assert got is not None
    assert got.status == ExecutorStatus.DEAD


def test_executor_heartbeat_with_resource_usage(repo: SqliteRepository) -> None:
    e = Executor(executor_id="cc-1", channel_type="claude-code")
    repo.register_executor(e)
    repo.heartbeat_executor("cc-1", resource_usage={"cpu": 0.5, "mem": 0.8})
    got = repo.get_executor("cc-1")
    assert got is not None
    assert got.metadata.get("resource_usage") == {"cpu": 0.5, "mem": 0.8}


def test_executor_token_revoke_idempotent(repo: SqliteRepository) -> None:
    token = ExecutorToken(name="tok-1", token_hash="abc123", token_raw="raw")
    repo.create_executor_token(token)
    assert repo.revoke_executor_token("tok-1") is True
    assert repo.revoke_executor_token("tok-1") is False
    assert repo.get_executor_token_by_hash("abc123") is None


# ── Discord Metadata ─────────────────────────────────────────

def test_discord_channel_crud(repo: SqliteRepository) -> None:
    guild = DiscordGuild(guild_id="g1", cogent_name="dr.gamma", name="Test Guild")
    repo.upsert_discord_guild(guild)

    ch = DiscordChannel(channel_id="c1", guild_id="g1", name="general", channel_type="text")
    repo.upsert_discord_channel(ch)

    got = repo.get_discord_channel("c1")
    assert got is not None
    assert got.name == "general"

    channels = repo.list_discord_channels("g1")
    assert len(channels) == 1

    repo.delete_discord_channel("c1")
    assert repo.get_discord_channel("c1") is None


def test_discord_guild_delete_cascades_channels(repo: SqliteRepository) -> None:
    guild = DiscordGuild(guild_id="g1", cogent_name="dr.gamma", name="Test")
    repo.upsert_discord_guild(guild)
    ch = DiscordChannel(channel_id="c1", guild_id="g1", name="ch", channel_type="text")
    repo.upsert_discord_channel(ch)

    repo.delete_discord_guild("g1")
    assert repo.get_discord_guild("g1") is None
    assert repo.get_discord_channel("c1") is None


# ── Clear operations ─────────────────────────────────────────

def test_clear_config_clears_processes_and_runs_preserves_alerts(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT)
    repo.upsert_process(p)
    run = Run(process=p.id)
    repo.create_run(run)
    repo.create_alert("warning", "test", "src", "msg")

    repo.clear_config()

    assert repo.get_process(p.id) is None
    assert repo.get_run(run.id) is None
    alerts = repo.list_alerts()
    assert len(alerts) == 1  # alerts preserved


def test_clear_all_resets_epoch(repo: SqliteRepository) -> None:
    repo.increment_epoch()
    assert repo.reboot_epoch == 1
    repo.clear_all()
    assert repo.reboot_epoch == 0


# ── Raw query/execute ────────────────────────────────────────

def test_raw_query_and_execute(repo: SqliteRepository) -> None:
    repo.set_meta("k", "v")
    rows = repo.query("SELECT * FROM cogos_meta WHERE key = :key", {"key": "k"})
    assert len(rows) == 1
    assert rows[0]["value"] == "v"

    count = repo.execute("DELETE FROM cogos_meta WHERE key = :key", {"key": "k"})
    assert count == 1


# ── Channel message wake logic ───────────────────────────────

def test_channel_message_wakes_waiting_process_without_wait_condition(repo: SqliteRepository) -> None:
    p = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    ch = Channel(name="inbox", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    msg = ChannelMessage(channel=ch.id, payload={"text": "wake up"})
    repo.append_channel_message(msg)

    got = repo.get_process(p.id)
    assert got is not None
    assert got.status == ProcessStatus.RUNNABLE


def test_channel_message_child_exit_resolves_wait_any(repo: SqliteRepository) -> None:
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    child = Process(name="child", mode=ProcessMode.ONE_SHOT, parent_process=parent.id)
    repo.upsert_process(child)

    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=parent.id, channel=ch.id)
    repo.create_handler(h)

    wc = WaitCondition(
        process=parent.id,
        type=WaitConditionType.WAIT_ANY,
        pending=[str(child.id)],
    )
    repo.create_wait_condition(wc)

    msg = ChannelMessage(
        channel=ch.id,
        sender_process=child.id,
        payload={"type": "child:exited"},
    )
    repo.append_channel_message(msg)

    got = repo.get_process(parent.id)
    assert got is not None
    assert got.status == ProcessStatus.RUNNABLE


def test_channel_message_child_exit_wait_all_not_done(repo: SqliteRepository) -> None:
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    child1 = Process(name="child1", mode=ProcessMode.ONE_SHOT, parent_process=parent.id)
    child2 = Process(name="child2", mode=ProcessMode.ONE_SHOT, parent_process=parent.id)
    repo.upsert_process(child1)
    repo.upsert_process(child2)

    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=parent.id, channel=ch.id)
    repo.create_handler(h)

    wc = WaitCondition(
        process=parent.id,
        type=WaitConditionType.WAIT_ALL,
        pending=[str(child1.id), str(child2.id)],
    )
    repo.create_wait_condition(wc)

    # First child exits — should NOT wake parent yet
    msg1 = ChannelMessage(
        channel=ch.id,
        sender_process=child1.id,
        payload={"type": "child:exited"},
    )
    repo.append_channel_message(msg1)

    got = repo.get_process(parent.id)
    assert got is not None
    assert got.status == ProcessStatus.WAITING

    # Second child exits — NOW wake parent
    msg2 = ChannelMessage(
        channel=ch.id,
        sender_process=child2.id,
        payload={"type": "child:exited"},
    )
    repo.append_channel_message(msg2)

    got = repo.get_process(parent.id)
    assert got is not None
    assert got.status == ProcessStatus.RUNNABLE


# ── Nudge callback ───────────────────────────────────────────

def test_nudge_callback_fires(tmp_path: Path) -> None:
    nudges: list[tuple] = []

    def on_nudge(url: str, body: str) -> None:
        nudges.append((url, body))

    repo = SqliteRepository(
        str(tmp_path),
        ingress_queue_url="http://localhost/queue",
        nudge_callback=on_nudge,
    )
    p = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    ch = Channel(name="ch", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    h = Handler(process=p.id, channel=ch.id)
    repo.create_handler(h)

    msg = ChannelMessage(channel=ch.id, payload={"text": "hi"})
    repo.append_channel_message(msg)

    assert len(nudges) >= 1


# ── JSON serialization edge cases ────────────────────────────

def test_json_serial_uuid_and_datetime(repo: SqliteRepository) -> None:
    p = Process(
        name="json-test",
        mode=ProcessMode.ONE_SHOT,
        metadata={"uuid_field": uuid4(), "dt_field": datetime.now(UTC), "decimal_field": Decimal("1.23")},
    )
    repo.upsert_process(p)
    got = repo.get_process(p.id)
    assert got is not None
    assert isinstance(got.metadata["uuid_field"], str)
    assert isinstance(got.metadata["dt_field"], str)
    assert isinstance(got.metadata["decimal_field"], float)


# ── Reload (no-op) ──────────────────────────────────────────

def test_reload_is_noop(repo: SqliteRepository) -> None:
    repo.set_meta("k", "v")
    repo.reload()
    assert repo.get_meta("k") is not None


# ── WAL mode and foreign keys ───────────────────────────────

def test_wal_mode_enabled(repo: SqliteRepository) -> None:
    result = repo._query("PRAGMA journal_mode")
    assert result[0]["journal_mode"] == "wal"


def test_foreign_keys_enabled(repo: SqliteRepository) -> None:
    result = repo._query("PRAGMA foreign_keys")
    assert result[0]["foreign_keys"] == 1

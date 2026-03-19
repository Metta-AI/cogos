from datetime import datetime, timezone
from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Cron,
    DeliveryStatus,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    RunStatus,
)
from cogos.runtime.ingress import dispatch_ready_processes
from cogos.runtime.schedule import apply_scheduled_messages
from cogtainer.lambdas.dispatcher.handler import _apply_system_ticks


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(
        name=name,
        mode=ProcessMode.DAEMON,
        status=status,
        runner="lambda",
    )


def _setup_channel_and_handler(repo, proc, channel_name="io:discord:dm"):
    """Create a channel + handler + message for the process."""
    ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name(channel_name)
    assert ch is not None
    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)
    msg = ChannelMessage(channel=ch.id, payload={"content": "hello"})
    repo.append_channel_message(msg)
    return ch, handler, msg


def test_match_messages_idempotent_per_handler(tmp_path):
    """append_channel_message creates inline deliveries; match_messages is a backstop
    that picks up handlers added after the message was written."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc1 = _daemon("discord-one")
    repo.upsert_process(proc1)

    ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    ch = repo.get_channel_by_name("io:discord:dm")
    assert ch is not None

    repo.create_handler(Handler(process=proc1.id, channel=ch.id))
    repo.append_channel_message(ChannelMessage(channel=ch.id, payload={"content": "hi"}))

    # Inline delivery already created by append_channel_message — backstop finds 0 new
    first = scheduler.match_messages()
    assert first.deliveries_created == 0

    # Add a second handler after the message — backstop should pick it up
    proc2 = _daemon("discord-two")
    repo.upsert_process(proc2)
    repo.create_handler(Handler(process=proc2.id, channel=ch.id))

    second = scheduler.match_messages()
    assert second.deliveries_created == 1
    assert second.deliveries[0].process_id == str(proc2.id)


def test_match_and_dispatch(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    ch, handler, msg = _setup_channel_and_handler(repo, proc)

    # Inline delivery already created by append_channel_message
    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE

    class _LambdaClient:
        def __init__(self) -> None:
            self.invocations: list[dict] = []

        def invoke(self, **kwargs):
            self.invocations.append(kwargs)
            return {"StatusCode": 202}

    lambda_client = _LambdaClient()
    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        lambda_client,
        "executor-fn",
        {proc.id},
    )

    assert dispatched == 1
    assert len(lambda_client.invocations) == 1
    assert len(repo.list_runs(process_id=proc.id)) == 1
    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNING
    delivery = next(iter(repo._deliveries.values()))
    assert delivery.status == DeliveryStatus.QUEUED


def test_dispatch_rolls_back_failed_invoke(tmp_path):
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("discord-daemon")
    repo.upsert_process(proc)
    _setup_channel_and_handler(repo, proc)

    scheduler.match_messages()

    class _LambdaClient:
        def invoke(self, **_kwargs):
            raise RuntimeError("invoke failed")

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        _LambdaClient(),
        "executor-fn",
        {proc.id},
    )

    assert dispatched == 0
    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE
    assert len(repo.get_pending_deliveries(proc.id)) == 1
    runs = repo.list_runs(process_id=proc.id)
    assert runs is not None
    assert len(runs) == 1
    assert runs[0].status == RunStatus.FAILED
    delivery = next(iter(repo._deliveries.values()))
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.run is None


def test_apply_system_ticks_wakes_channel_subscribers(tmp_path):
    repo = _repo(tmp_path)
    proc = _daemon("hourly")
    repo.upsert_process(proc)

    channel = Channel(name="system:tick:hour", channel_type=ChannelType.NAMED)
    repo.upsert_channel(channel)
    channel = repo.get_channel_by_name("system:tick:hour")
    assert channel is not None
    repo.create_handler(Handler(process=proc.id, channel=channel.id))

    _apply_system_ticks(repo, now=datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc))

    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE
    assert len(repo.get_pending_deliveries(proc.id)) == 1


def test_apply_scheduled_messages_emits_matching_cron_channels(tmp_path):
    repo = _repo(tmp_path)
    proc = _daemon("cron-worker")
    repo.upsert_process(proc)

    channel = Channel(name="check:health", channel_type=ChannelType.NAMED)
    repo.upsert_channel(channel)
    channel = repo.get_channel_by_name("check:health")
    assert channel is not None
    repo.create_handler(Handler(process=proc.id, channel=channel.id))
    repo.upsert_cron(
        Cron(
            expression="15 8 * * *",
            channel_name="check:health",
            payload={"kind": "cron"},
        )
    )

    emitted = apply_scheduled_messages(
        repo,
        now=datetime(2026, 3, 13, 8, 15, tzinfo=timezone.utc),
    )

    assert emitted >= 2
    _tmp_get_process = repo.get_process(proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE
    messages = repo.list_channel_messages(channel.id)
    assert messages is not None
    assert messages[-1].payload == {"kind": "cron"}

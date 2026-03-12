"""Tests for channel-based scheduler delivery."""
from uuid import UUID, uuid4

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path))


def _daemon(name: str, *, status: ProcessStatus = ProcessStatus.WAITING) -> Process:
    return Process(name=name, mode=ProcessMode.DAEMON, status=status, runner="lambda")


def test_channel_message_auto_creates_delivery(tmp_path):
    """Appending a message to a channel with a handler creates a delivery."""
    repo = _repo(tmp_path)

    proc = _daemon("worker")
    repo.upsert_process(proc)

    owner = _daemon("owner")
    repo.upsert_process(owner)

    ch = Channel(name="io:discord:dm", owner_process=owner.id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    # Append message -- should auto-create delivery and wake process
    msg = ChannelMessage(channel=ch.id, sender_process=owner.id, payload={"content": "hello"})
    repo.append_channel_message(msg)

    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE
    deliveries = repo.get_pending_deliveries(proc.id)
    assert len(deliveries) >= 1


def test_match_channel_messages_backstop(tmp_path):
    """Scheduler backstop finds undelivered channel messages."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("worker")
    repo.upsert_process(proc)

    owner = _daemon("owner")
    repo.upsert_process(owner)

    ch = Channel(name="io:discord:dm", owner_process=owner.id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    # Append message (auto-delivery should work, but test backstop too)
    msg = ChannelMessage(channel=ch.id, sender_process=owner.id, payload={"content": "hello"})
    repo.append_channel_message(msg)

    # Backstop should find no NEW undelivered messages (auto-delivery already handled it)
    result = scheduler.match_channel_messages()
    # The auto-delivery already created the delivery, so backstop finds 0 new
    assert result.deliveries_created == 0


def test_no_handler_no_delivery(tmp_path):
    """Message on a channel with no handlers creates no deliveries."""
    repo = _repo(tmp_path)

    owner = _daemon("owner")
    repo.upsert_process(owner)

    ch = Channel(name="metrics", owner_process=owner.id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    msg = ChannelMessage(channel=ch.id, sender_process=owner.id, payload={"value": 42})
    repo.append_channel_message(msg)

    # No handlers, so no deliveries
    assert repo.get_process(owner.id).status == ProcessStatus.WAITING


def test_backstop_creates_missing_deliveries(tmp_path):
    """Backstop creates deliveries for messages that missed auto-delivery."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    proc = _daemon("worker")
    repo.upsert_process(proc)

    owner = _daemon("owner")
    repo.upsert_process(owner)

    ch = Channel(name="io:slack:dm", owner_process=owner.id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    # Append message BEFORE handler exists (no auto-delivery)
    msg = ChannelMessage(channel=ch.id, sender_process=owner.id, payload={"content": "early"})
    repo.append_channel_message(msg)
    assert repo.get_process(proc.id).status == ProcessStatus.WAITING

    # Now create handler
    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    # Backstop should pick up the missed message
    result = scheduler.match_channel_messages()
    assert result.deliveries_created == 1
    assert result.deliveries[0].process_id == str(proc.id)
    assert repo.get_process(proc.id).status == ProcessStatus.RUNNABLE


def test_multiple_handlers_on_same_channel(tmp_path):
    """Multiple handlers on the same channel each get a delivery."""
    repo = _repo(tmp_path)

    proc1 = _daemon("worker-1")
    repo.upsert_process(proc1)

    proc2 = _daemon("worker-2")
    repo.upsert_process(proc2)

    owner = _daemon("owner")
    repo.upsert_process(owner)

    ch = Channel(name="io:events", owner_process=owner.id, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    repo.create_handler(Handler(process=proc1.id, channel=ch.id))
    repo.create_handler(Handler(process=proc2.id, channel=ch.id))

    msg = ChannelMessage(channel=ch.id, sender_process=owner.id, payload={"data": "test"})
    repo.append_channel_message(msg)

    assert repo.get_process(proc1.id).status == ProcessStatus.RUNNABLE
    assert repo.get_process(proc2.id).status == ProcessStatus.RUNNABLE

    d1 = repo.get_pending_deliveries(proc1.id)
    d2 = repo.get_pending_deliveries(proc2.id)
    assert len(d1) == 1
    assert len(d2) == 1

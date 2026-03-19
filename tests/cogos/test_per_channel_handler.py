"""Integration test for per-channel Discord sub-handler flow."""

from cogos.capabilities.procs import ProcsCapability
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


def test_child_receives_delivery_on_fine_grained_channel(tmp_path):
    """After parent spawns a child subscribed to a fine-grained channel,
    new messages on that channel create deliveries for the child."""
    repo = _repo(tmp_path)

    # Create parent process (the discord-handler)
    parent = Process(
        name="discord-handler",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        runner="lambda",
    )
    repo.upsert_process(parent)

    # Create catch-all and fine-grained channels
    catch_all = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
    repo.upsert_channel(catch_all)

    fine = Channel(name="io:discord:message:12345", channel_type=ChannelType.NAMED)
    repo.upsert_channel(fine)

    # Parent has a handler on catch-all
    repo.create_handler(Handler(process=parent.id, channel=catch_all.id))

    # Parent spawns a child subscribed to fine-grained channel
    procs = ProcsCapability(repo, parent.id)
    child_handle = procs.spawn(
        name="discord-handler:12345",
        content="Handle messages from channel 12345",
        subscribe="io:discord:message:12345",
    )
    assert not hasattr(child_handle, "error"), f"Spawn failed: {child_handle}"

    # Simulate bridge writing a message to both channels
    payload = {"content": "hello", "channel_id": "12345", "author_id": "42"}
    repo.append_channel_message(
        ChannelMessage(
            channel=catch_all.id,
            sender_process=None,
            payload=payload,
        )
    )
    repo.append_channel_message(
        ChannelMessage(
            channel=fine.id,
            sender_process=None,
            payload=payload,
        )
    )

    # Child should have a pending delivery on the fine-grained channel
    child_proc = repo.get_process_by_name("discord-handler:12345")
    assert child_proc is not None
    child_deliveries = repo.get_pending_deliveries(child_proc.id)
    assert child_deliveries is not None
    assert len(child_deliveries) >= 1

    # Parent should also have a pending delivery on catch-all
    parent_deliveries = repo.get_pending_deliveries(parent.id)
    assert parent_deliveries is not None
    assert len(parent_deliveries) >= 1

    # Both should be RUNNABLE
    _tmp_get_process = repo.get_process(child_proc.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE
    _tmp_get_process = repo.get_process(parent.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.RUNNABLE

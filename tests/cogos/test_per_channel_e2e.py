"""End-to-end test for per-channel Discord sub-handler routing.

Boots cogos image, simulates Discord DM flow, verifies:
1. Parent handler wakes on first DM
2. Parent spawns a daemon child subscribed to the fine-grained channel
3. On second DM, child has its own delivery on the fine-grained channel
4. Idle reaping cleans up the child after timeout
"""

from uuid import UUID

from cogos.capabilities.procs import ProcsCapability
from cogos.capabilities.scheduler import SchedulerCapability
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
from cogos.runtime.local import run_local_tick


def _repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(str(tmp_path / "db"))


def _dm_payload(author_id: str = "42", content: str = "hello") -> dict:
    return {
        "content": content,
        "author": "tester",
        "author_id": author_id,
        "channel_id": "999",
        "message_type": "discord:dm",
        "is_dm": True,
        "is_mention": False,
        "attachments": [],
        "embeds": [],
    }


def _simulate_bridge_dm(repo: SqliteRepository, payload: dict) -> None:
    """Simulate what the bridge does: write to catch-all + fine-grained channel."""
    author_id = payload["author_id"]

    # Catch-all
    catch_all = repo.get_channel_by_name("io:discord:dm")
    if catch_all is None:
        catch_all = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
        repo.upsert_channel(catch_all)
        catch_all = repo.get_channel_by_name("io:discord:dm")
        assert catch_all is not None
    repo.append_channel_message(
        ChannelMessage(
            channel=catch_all.id,
            sender_process=None,
            payload=payload,
        )
    )

    # Fine-grained
    fine_name = f"io:discord:dm:{author_id}"
    fine = repo.get_channel_by_name(fine_name)
    if fine is None:
        fine = Channel(name=fine_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(fine)
        fine = repo.get_channel_by_name(fine_name)
        assert fine is not None
    repo.append_channel_message(
        ChannelMessage(
            channel=fine.id,
            sender_process=None,
            payload=payload,
        )
    )


def test_per_channel_dm_routing_full_flow(tmp_path):
    """Full flow: boot image, send DM, parent spawns child, second DM goes to child."""
    repo = _repo(tmp_path)

    # Create the discord-handle-message daemon and its handler channels
    # (In production these are spawned by init.py at runtime; here we set them up directly.)
    handler_channel_names = ["io:discord:dm", "io:discord:message", "io:discord:mention"]
    for ch_name in handler_channel_names:
        repo.upsert_channel(Channel(name=ch_name, channel_type=ChannelType.NAMED))

    parent = Process(
        name="discord-handle-message",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        content="Discord dispatch handler",
        required_tags=[],
    )
    parent_id = repo.upsert_process(parent)
    parent = repo.get_process(parent_id)
    assert parent is not None

    for ch_name in handler_channel_names:
        ch = repo.get_channel_by_name(ch_name)
        assert ch is not None
        repo.create_handler(Handler(process=parent_id, channel=ch.id, enabled=True))

    assert parent is not None
    assert parent.mode == ProcessMode.DAEMON
    assert parent.status == ProcessStatus.WAITING

    # Send first DM — simulates bridge dual-write
    _simulate_bridge_dm(repo, _dm_payload(author_id="42", content="hello"))

    # Parent should now be RUNNABLE (got delivery on catch-all)
    parent = repo.get_process(parent.id)
    assert parent is not None
    assert parent.status == ProcessStatus.RUNNABLE

    # Run a tick with a fake executor that simulates what the LLM would do:
    # check for child, spawn one if missing
    def _parent_spawns_child(process, event_data, run, config, repo, **kwargs):
        """Simulate parent's LLM behavior: spawn a child for this DM author."""
        payload = event_data.get("payload", {})
        author_id = payload.get("author_id")
        if not author_id:
            return run

        child_name = f"discord-dm:{author_id}"
        existing = repo.get_process_by_name(child_name)
        if existing and existing.status != ProcessStatus.DISABLED:
            # Child already exists, skip
            return run

        # Spawn child — replicate what the LLM would call via procs capability
        procs = ProcsCapability(repo, process.id)
        procs.spawn(
            name=child_name,
            content=f"DM handler for user {author_id}",
            mode="daemon",
            idle_timeout_ms=60_000,
            subscribe=f"io:discord:dm:{author_id}",
        )
        return run

    executed = run_local_tick(repo, None, execute_fn=_parent_spawns_child)
    assert executed >= 1

    # Verify child was spawned
    child = repo.get_process_by_name("discord-dm:42")
    assert child is not None
    assert child.mode == ProcessMode.DAEMON
    assert child.parent_process == parent.id
    assert child.idle_timeout_ms == 60_000

    # Verify child has a handler on the fine-grained channel
    child_handlers = repo.list_handlers(process_id=child.id)
    assert child_handlers is not None
    child_handler_channels = set()
    for h in child_handlers:
        assert h.channel is not None
        ch = repo.get_channel(h.channel)
        assert ch is not None
        if ch:
            child_handler_channels.add(ch.name)
    assert "io:discord:dm:42" in child_handler_channels

    # Send second DM from same author
    _simulate_bridge_dm(repo, _dm_payload(author_id="42", content="second message"))

    # Child should have pending deliveries on the fine-grained channel
    child = repo.get_process(child.id)
    assert child is not None
    child_deliveries = repo.get_pending_deliveries(child.id)
    assert child_deliveries is not None
    assert len(child_deliveries) >= 1
    assert child.status == ProcessStatus.RUNNABLE


def test_idle_reaping_is_noop(tmp_path):
    """Idle reaping is a no-op — daemons stay alive until killed."""
    repo = _repo(tmp_path)
    scheduler = SchedulerCapability(repo, UUID(int=0))

    child = Process(
        name="discord-dm:42",
        mode=ProcessMode.DAEMON,
        status=ProcessStatus.WAITING,
        required_tags=[],
        idle_timeout_ms=1,
    )
    repo.upsert_process(child)

    result = scheduler.reap_idle_processes()
    assert result.reaped_count == 0
    _tmp_get_process = repo.get_process(child.id)
    assert _tmp_get_process is not None
    assert _tmp_get_process.status == ProcessStatus.WAITING

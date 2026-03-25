"""Tests for LocalIngressQueue and its integration with SqliteRepository + local_dispatcher."""

from __future__ import annotations

import json

import pytest

from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
)
from cogos.db.sqlite_repository import SqliteRepository
from cogos.runtime.local_ingress_queue import LocalIngressQueue

# ── Unit tests ──────────────────────────────────────────────


def test_send_and_drain():
    q = LocalIngressQueue()
    q.send("local://ingress", json.dumps({"source": "channel_message", "process_id": "aaa"}))
    q.send("local://ingress", json.dumps({"source": "channel_message", "process_id": "bbb"}))

    msgs = q.drain()
    assert len(msgs) == 2
    assert msgs[0]["process_id"] == "aaa"
    assert msgs[1]["process_id"] == "bbb"
    assert q.drain() == []


def test_drain_respects_max_messages():
    q = LocalIngressQueue()
    for i in range(10):
        q.send("local://ingress", json.dumps({"n": i}))
    assert len(q.drain(max_messages=3)) == 3
    assert q.pending == 7


def test_wait_returns_none_on_timeout():
    q = LocalIngressQueue()
    assert q.wait(timeout=0.01) is None


def test_wait_returns_message():
    q = LocalIngressQueue()
    q.send("local://ingress", json.dumps({"hello": "world"}))
    msg = q.wait(timeout=0.1)
    assert msg is not None
    assert msg["hello"] == "world"


def test_full_queue_drops_message():
    q = LocalIngressQueue(maxsize=2)
    q.send("local://ingress", json.dumps({"n": 1}))
    q.send("local://ingress", json.dumps({"n": 2}))
    q.send("local://ingress", json.dumps({"n": 3}))  # dropped
    assert q.pending == 2


def test_wait_for_nudge_returns_true_on_send():
    """wait_for_nudge returns True immediately when a message has been enqueued."""
    q = LocalIngressQueue()
    q.send("local://ingress", json.dumps({"process_id": "abc"}))
    assert q.wait_for_nudge(timeout=0.01) is True


def test_wait_for_nudge_returns_false_on_timeout():
    """wait_for_nudge returns False when no message arrives before timeout."""
    q = LocalIngressQueue()
    assert q.wait_for_nudge(timeout=0.01) is False


def test_wait_for_nudge_clears_event():
    """After wait_for_nudge returns, the event is cleared so the next call blocks."""
    q = LocalIngressQueue()
    q.send("local://ingress", json.dumps({"n": 1}))
    assert q.wait_for_nudge(timeout=0.01) is True
    # Event cleared — should timeout now (no new send)
    assert q.wait_for_nudge(timeout=0.01) is False


# ── Integration: nudge fires on channel message ────────────


@pytest.fixture
def repo(tmp_path) -> SqliteRepository:
    return SqliteRepository(data_dir=str(tmp_path))


def test_channel_message_nudges_ingress(tmp_path):
    """When a channel message wakes a WAITING process, the local ingress queue gets nudged."""
    q = LocalIngressQueue()
    repo = SqliteRepository(
        data_dir=str(tmp_path),
        ingress_queue_url="local://ingress",
        nudge_callback=q.send,
    )

    # Set up a daemon process in WAITING state with a handler on a channel
    proc = Process(name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(proc)

    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    # Send a channel message — should create delivery, wake process, and nudge
    msg = ChannelMessage(channel=ch.id, payload={"type": "test"})
    repo.append_channel_message(msg)

    # Process should now be RUNNABLE
    updated = repo.get_process(proc.id)
    assert updated is not None
    assert updated.status == ProcessStatus.RUNNABLE

    # Ingress queue should have exactly one nudge with the process ID
    nudges = q.drain()
    assert len(nudges) == 1
    assert nudges[0]["process_id"] == str(proc.id)
    assert nudges[0]["source"] == "channel_message"


def test_no_nudge_when_already_runnable(tmp_path):
    """A process already RUNNABLE should not be nudged again."""
    q = LocalIngressQueue()
    repo = SqliteRepository(
        data_dir=str(tmp_path),
        ingress_queue_url="local://ingress",
        nudge_callback=q.send,
    )

    proc = Process(name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNABLE)
    repo.upsert_process(proc)

    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    msg = ChannelMessage(channel=ch.id, payload={"type": "test"})
    repo.append_channel_message(msg)

    # No nudge because process was already RUNNABLE
    assert q.drain() == []


def test_no_nudge_without_callback(repo):
    """Without a nudge callback, append_channel_message still works normally."""
    proc = Process(name="worker", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(proc)

    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)

    handler = Handler(process=proc.id, channel=ch.id)
    repo.create_handler(handler)

    msg = ChannelMessage(channel=ch.id, payload={"type": "test"})
    msg_id = repo.append_channel_message(msg)

    # Process still wakes up, just no nudge
    updated = repo.get_process(proc.id)
    assert updated is not None
    assert updated.status == ProcessStatus.RUNNABLE
    assert msg_id is not None

"""Tests for spawn() subscribe parameter — binds child to a channel handler."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.capabilities.procs import ProcsCapability, ProcessError
from cogos.db.models import Channel, ChannelType


def _make_cap_model(name="files"):
    m = MagicMock()
    m.id = uuid4()
    m.enabled = True
    m.name = name
    return m


def test_spawn_with_subscribe_creates_handler():
    """spawn(subscribe="ch-name") should create a Handler for the child subscribe channel."""
    repo = MagicMock()
    parent_pid = uuid4()
    child_id = uuid4()
    repo.upsert_process.return_value = child_id

    ch = Channel(name="io:discord:message:12345", channel_type=ChannelType.NAMED)
    repo.get_channel_by_name.return_value = ch
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work", subscribe="io:discord:message:12345")

    assert not isinstance(result, ProcessError)
    repo.create_handler.assert_called_once()
    child_handler = repo.create_handler.call_args.args[0]
    assert child_handler.process == child_id
    assert child_handler.channel == ch.id


def test_spawn_with_subscribe_channel_not_found():
    """spawn(subscribe="missing") should return error if channel doesn't exist."""
    repo = MagicMock()
    parent_pid = uuid4()
    repo.upsert_process.return_value = uuid4()
    repo.get_channel_by_name.return_value = None
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work", subscribe="no-such-channel")

    assert isinstance(result, ProcessError)
    assert "not found" in result.error.lower()


def test_spawn_without_subscribe_creates_no_handler():
    """spawn() without subscribe should not create any handlers (wait() creates them on demand)."""
    repo = MagicMock()
    parent_pid = uuid4()
    child_id = uuid4()
    repo.upsert_process.return_value = child_id
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work")

    assert not isinstance(result, ProcessError)
    repo.create_handler.assert_not_called()

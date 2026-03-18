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
    """spawn(subscribe="ch-name") should create Handlers for both parent (recv) and child (subscribe)."""
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
    assert repo.create_handler.call_count == 2
    # First call: parent handler on recv channel
    parent_handler = repo.create_handler.call_args_list[0].args[0]
    assert parent_handler.process == parent_pid
    # Second call: child subscribe handler
    child_handler = repo.create_handler.call_args_list[1].args[0]
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


def test_spawn_without_subscribe_creates_parent_handler_only():
    """spawn() without subscribe should create a parent handler on recv channel only."""
    repo = MagicMock()
    parent_pid = uuid4()
    child_id = uuid4()
    repo.upsert_process.return_value = child_id
    repo.list_process_capabilities.return_value = []

    procs = ProcsCapability(repo, parent_pid)
    result = procs.spawn(name="child", content="work")

    assert not isinstance(result, ProcessError)
    repo.create_handler.assert_called_once()
    handler = repo.create_handler.call_args.args[0]
    assert handler.process == parent_pid

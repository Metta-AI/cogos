"""Tests for ChannelsCapability."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.channels import ChannelError, ChannelsCapability
from cogos.db.models import Channel, ChannelMessage, ChannelType, Schema


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.list_schemas.return_value = []
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestCreate:
    def test_create_with_inline_schema(self, repo, pid):
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema={"value": "number"})
        assert not isinstance(result, ChannelError)
        assert result.name == "metrics"
        repo.upsert_channel.assert_called_once()

    def test_create_with_named_schema(self, repo, pid):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.get_schema_by_name.return_value = s
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema="metrics")
        assert not isinstance(result, ChannelError)
        assert result.name == "metrics"

    def test_create_missing_schema_ref(self, repo, pid):
        repo.get_schema_by_name.return_value = None
        cap = ChannelsCapability(repo, pid)
        result = cap.create("metrics", schema="nonexistent")
        assert hasattr(result, "error")


class TestSendAndRead:
    def test_send_valid(self, repo, pid):
        ch = Channel(
            name="ch1", owner_process=pid, channel_type=ChannelType.NAMED, inline_schema={"fields": {"body": "string"}}
        )
        repo.get_channel_by_name.return_value = ch
        repo.append_channel_message.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.send("ch1", {"body": "hello"})
        assert hasattr(result, "id")

    def test_send_invalid_payload(self, repo, pid):
        ch = Channel(
            name="ch1", owner_process=pid, channel_type=ChannelType.NAMED, inline_schema={"fields": {"body": "string"}}
        )
        repo.get_channel_by_name.return_value = ch
        cap = ChannelsCapability(repo, pid)
        result = cap.send("ch1", {"body": 123})
        assert hasattr(result, "error")

    def test_send_closed_channel(self, repo, pid):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED, closed_at=now)
        repo.get_channel_by_name.return_value = ch
        cap = ChannelsCapability(repo, pid)
        result = cap.send("ch1", {"body": "hello"})
        assert hasattr(result, "error")

    def test_read(self, repo, pid):
        ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=ch.id, sender_process=pid, payload={"body": "hi"}),
        ]
        cap = ChannelsCapability(repo, pid)
        result = cap.read("ch1")
        assert not isinstance(result, ChannelError)
        assert len(result) == 1


class TestSubscribe:
    def test_subscribe_creates_handler(self, repo, pid):
        ch = Channel(name="ch1", owner_process=uuid4(), channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.create_handler.return_value = uuid4()
        cap = ChannelsCapability(repo, pid)
        result = cap.subscribe("ch1")
        assert hasattr(result, "handler_id")
        repo.create_handler.assert_called_once()


class TestClose:
    def test_close_by_owner(self, repo, pid):
        ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.close_channel.return_value = True
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        closed_ch = Channel(name="ch1", owner_process=pid, channel_type=ChannelType.NAMED, closed_at=now)
        repo.get_channel.return_value = closed_ch
        cap = ChannelsCapability(repo, pid)
        result = cap.close("ch1")
        assert not isinstance(result, ChannelError)
        assert result.closed_at is not None

    def test_close_by_non_owner(self, repo, pid):
        ch = Channel(name="ch1", owner_process=uuid4(), channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        cap = ChannelsCapability(repo, pid)
        result = cap.close("ch1")
        assert hasattr(result, "error")


class TestScoping:
    def test_scoped_create_allowed(self, repo, pid):
        repo.upsert_channel.return_value = uuid4()
        cap = ChannelsCapability(repo, pid).scope(ops=["create", "list", "get"])
        cap.create("metrics", schema={"value": "number"})

    def test_scoped_create_denied(self, repo, pid):
        cap = ChannelsCapability(repo, pid).scope(ops=["list", "get"])
        with pytest.raises(PermissionError):
            cap.create("metrics", schema={"value": "number"})

    def test_scoped_name_pattern(self, repo, pid):
        cap = ChannelsCapability(repo, pid).scope(names=["metrics*"])
        ch = Channel(name="metrics-v1", owner_process=pid, channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch
        repo.list_channel_messages.return_value = []
        cap.read("metrics-v1")  # should not raise
        with pytest.raises(PermissionError):
            cap.read("alerts")

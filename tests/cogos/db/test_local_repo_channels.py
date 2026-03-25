"""Tests for SqliteRepository channel and schema CRUD."""

import pytest

from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    Handler,
    Process,
    ProcessMode,
    ProcessStatus,
    Schema,
)
from cogos.db.sqlite_repository import SqliteRepository


@pytest.fixture
def repo(tmp_path):
    return SqliteRepository(str(tmp_path))


@pytest.fixture
def process(repo):
    p = Process(name="test-proc", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(p)
    return p


class TestSchemaCRUD:
    def test_upsert_and_get(self, repo):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        sid = repo.upsert_schema(s)
        assert sid == s.id
        got = repo.get_schema(sid)
        assert got.name == "metrics"

    def test_get_by_name(self, repo):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.upsert_schema(s)
        got = repo.get_schema_by_name("metrics")
        assert got is not None
        assert got.id == s.id

    def test_list_schemas(self, repo):
        repo.upsert_schema(Schema(name="a", definition={}))
        repo.upsert_schema(Schema(name="b", definition={}))
        assert len(repo.list_schemas()) == 2

    def test_upsert_by_name(self, repo):
        s1 = Schema(name="metrics", definition={"fields": {"v": "number"}})
        repo.upsert_schema(s1)
        s2 = Schema(name="metrics", definition={"fields": {"v": "string"}})
        repo.upsert_schema(s2)
        assert len(repo.list_schemas()) == 1
        got = repo.get_schema_by_name("metrics")
        assert got.definition == {"fields": {"v": "string"}}


class TestChannelCRUD:
    def test_create_and_get(self, repo, process):
        ch = Channel(name="process:test-proc", owner_process=process.id, channel_type=ChannelType.IMPLICIT)
        cid = repo.upsert_channel(ch)
        got = repo.get_channel(cid)
        assert got.name == "process:test-proc"

    def test_get_by_name(self, repo, process):
        ch = Channel(name="my-channel", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        got = repo.get_channel_by_name("my-channel")
        assert got is not None

    def test_list_channels(self, repo, process):
        # process fixture auto-creates 3 io channels (stdin, stdout, stderr)
        baseline = len(repo.list_channels())
        repo.upsert_channel(Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED))
        repo.upsert_channel(Channel(name="ch2", owner_process=process.id, channel_type=ChannelType.NAMED))
        assert len(repo.list_channels()) == baseline + 2

    def test_list_channels_by_owner(self, repo, process):
        baseline = len(repo.list_channels(owner_process=process.id))
        p2 = Process(name="other", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.WAITING)
        repo.upsert_process(p2)
        _baseline_p2 = len(repo.list_channels(owner_process=p2.id))
        repo.upsert_channel(Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED))
        repo.upsert_channel(Channel(name="ch2", owner_process=p2.id, channel_type=ChannelType.NAMED))
        assert len(repo.list_channels(owner_process=process.id)) == baseline + 1

    def test_close_channel(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        repo.close_channel(ch.id)
        got = repo.get_channel(ch.id)
        assert got.closed_at is not None


class TestChannelMessageCRUD:
    def test_append_and_list(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        msg = ChannelMessage(channel=ch.id, sender_process=process.id, payload={"body": "hello"})
        mid = repo.append_channel_message(msg)
        assert mid == msg.id
        msgs = repo.list_channel_messages(ch.id)
        assert len(msgs) == 1
        assert msgs[0].payload == {"body": "hello"}

    def test_list_with_limit(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        for i in range(5):
            repo.append_channel_message(
                ChannelMessage(channel=ch.id, sender_process=process.id, payload={"i": i})
            )
        assert len(repo.list_channel_messages(ch.id, limit=3)) == 3


class TestHandlerWithChannel:
    def test_handler_binds_to_channel(self, repo, process):
        ch = Channel(name="ch1", owner_process=process.id, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
        h = Handler(process=process.id, channel=ch.id)
        hid = repo.create_handler(h)
        handlers = repo.match_handlers_by_channel(ch.id)
        assert len(handlers) == 1
        assert handlers[0].id == hid

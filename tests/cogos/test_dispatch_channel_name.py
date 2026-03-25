"""Test that build_dispatch_event includes channel_name."""

from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.db.sqlite_repository import SqliteRepository
from cogos.runtime.dispatch import build_dispatch_event


class _FakeDispatch:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_channel_name_included(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    ch = Channel(name="myapp:tick", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    msg = ChannelMessage(channel=ch.id, sender_process=None, payload={"x": 1})
    repo.append_channel_message(msg)

    dispatch = _FakeDispatch(
        process_id="p1", run_id="r1", message_id=str(msg.id), trace_id=None,
    )
    event = build_dispatch_event(repo, dispatch)
    assert event["channel_name"] == "myapp:tick"
    assert event["payload"] == {"x": 1}


def test_channel_name_none_without_message(tmp_path):
    repo = SqliteRepository(str(tmp_path))
    dispatch = _FakeDispatch(
        process_id="p1", run_id="r1", message_id=None, trace_id=None,
    )
    event = build_dispatch_event(repo, dispatch)
    assert event["channel_name"] is None

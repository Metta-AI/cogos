"""Tests for shell channel commands."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, ChannelType
from cogos.shell.commands import CommandRegistry, ShellState
from cogos.shell.commands.channels import register


def _setup(tmp_path):
    repo = LocalRepository(str(tmp_path))
    ch = Channel(name="events", channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    repo.append_channel_message(
        ChannelMessage(
            channel=ch.id,
            sender_process=None,
            payload={"type": "test", "data": "hello"},
        )
    )
    state = ShellState(cogent_name="test", repo=repo, cwd="")
    reg = CommandRegistry()
    register(reg)
    return state, reg, repo


def test_ch_ls(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ch ls")
    assert output is not None
    assert "events" in output


def test_ch_send(tmp_path):
    state, reg, repo = _setup(tmp_path)
    reg.dispatch(state, 'ch send events {"type":"ping"}')
    ch = repo.get_channel_by_name("events")
    assert ch is not None
    msgs = repo.list_channel_messages(ch.id)
    assert len(msgs) == 2
    assert msgs[-1].payload["type"] == "ping"


def test_ch_log(tmp_path):
    state, reg, _ = _setup(tmp_path)
    output = reg.dispatch(state, "ch log events")
    assert output is not None
    assert "test" in output
    assert "hello" in output

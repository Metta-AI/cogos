from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelType
from cogos.io.discord import bridge as bridge_mod
from cogos.io.discord.bridge import DiscordBridge, _reply_queue_latency_ms


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge._typing_tasks = {}
    bridge._s3_client = None
    bridge._blob_bucket = ""
    bridge._pending_dms = {}
    bridge._alerted_dm_ids = set()
    return bridge


@pytest.mark.anyio
async def test_handle_dm_stops_typing_on_dm_channel():
    bridge = _make_bridge()
    bridge._stop_typing = MagicMock()
    bridge._log_reply_send_latency = MagicMock()

    mock_user = AsyncMock()
    mock_dm_channel = AsyncMock()
    mock_dm_channel.id = 444
    mock_user.create_dm.return_value = mock_dm_channel
    bridge.client.fetch_user = AsyncMock(return_value=mock_user)

    body = {
        "user_id": "777",
        "content": "hi there",
        "_meta": {"queued_at_ms": 1000, "trace_id": "trace-1"},
    }
    await bridge._handle_dm(body)

    bridge.client.fetch_user.assert_called_once_with(777)
    mock_user.create_dm.assert_called_once()
    bridge._stop_typing.assert_called_once_with(444)
    mock_dm_channel.send.assert_called_once_with("hi there")
    bridge._log_reply_send_latency.assert_called_once_with(body, msg_type="dm", target_id=444)


def test_reply_queue_latency_ms_uses_enqueued_timestamp():
    with patch("cogos.io.discord.bridge.time.time", return_value=10.0):
        assert _reply_queue_latency_ms({"_meta": {"queued_at_ms": "9500"}}) == 500


@pytest.mark.anyio
async def test_relay_to_db_recreates_missing_system_channel():
    bridge = _make_bridge()
    bridge.client.user = None  # type: ignore[assignment]
    bridge._start_typing = MagicMock()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    created_channel = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
    fine_channel = Channel(name="io:discord:dm:456", channel_type=ChannelType.NAMED)

    call_count = {"dm": 0, "fine": 0}

    def _get_channel(name):
        if name == "io:discord:dm":
            call_count["dm"] += 1
            # First call returns None (missing), second returns created channel
            return None if call_count["dm"] == 1 else created_channel
        if name == "io:discord:dm:456":
            call_count["fine"] += 1
            return None if call_count["fine"] == 1 else fine_channel
        return None

    repo.get_channel_by_name.side_effect = _get_channel

    msg = MagicMock(spec=discord.Message)
    msg.id = 123
    msg.content = "hello"
    msg.attachments = []
    msg.embeds = []
    msg.reference = None
    msg.guild = None
    msg.author = MagicMock()
    msg.author.id = 456
    msg.author.bot = False
    msg.channel = MagicMock(spec=discord.DMChannel)
    msg.channel.id = 789

    await bridge._relay_to_db(msg)

    # Catch-all channel should have been upserted (and fine-grained too)
    upsert_names = [c.args[0].name for c in repo.upsert_channel.call_args_list]
    assert "io:discord:dm" in upsert_names
    upserted_channel = next(c.args[0] for c in repo.upsert_channel.call_args_list if c.args[0].name == "io:discord:dm")
    assert upserted_channel.owner_process is None
    assert upserted_channel.channel_type == ChannelType.NAMED

    # 2 writes: catch-all + fine-grained channel
    assert repo.append_channel_message.call_count == 2
    channel_message = repo.append_channel_message.call_args_list[0].args[0]
    assert channel_message.channel == created_channel.id
    assert channel_message.sender_process is None
    assert channel_message.payload["message_type"] == "discord:dm"

    bridge._start_typing.assert_called_once_with(msg.channel)


def test_bridge_uses_local_repository_when_requested(monkeypatch, tmp_path):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def event(self, fn):
            return fn

    monkeypatch.setenv("USE_LOCAL_DB", "1")
    monkeypatch.setenv("COGENT_NAME", "local")
    monkeypatch.setenv("COGENT_LOCAL_DATA", str(tmp_path))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(bridge_mod.boto3, "client", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(bridge_mod.discord, "Client", _FakeClient)

    bridge = DiscordBridge()

    assert isinstance(bridge._get_repo(), LocalRepository)

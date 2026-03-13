"""Tests for Discord bridge service."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogos.io.discord.bridge import DiscordBridge, _make_message_payload


# ---------------------------------------------------------------------------
# Helpers to build fake Discord objects
# ---------------------------------------------------------------------------


def _make_author(*, name="testuser", id_=42):
    author = MagicMock()
    author.__str__ = lambda self: name
    author.id = id_
    return author


def _make_message(
    *,
    content="hello",
    author=None,
    channel_id=100,
    guild_id=200,
    message_id=300,
    attachments=None,
    embeds=None,
    reference=None,
    is_dm=False,
    is_thread=False,
    parent_channel_id=None,
    created_at=None,
):
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.author = author or _make_author()
    msg.id = message_id
    msg.attachments = attachments or []
    msg.embeds = embeds or []
    msg.reference = reference
    msg.created_at = created_at or datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Channel setup
    if is_dm:
        ch = MagicMock(spec=discord.DMChannel)
        ch.id = channel_id
        msg.guild = None
    elif is_thread:
        ch = MagicMock(spec=discord.Thread)
        ch.id = channel_id
        ch.parent_id = parent_channel_id or 999
        guild = MagicMock()
        guild.id = guild_id
        msg.guild = guild
    else:
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = channel_id
        guild = MagicMock()
        guild.id = guild_id
        msg.guild = guild

    msg.channel = ch
    return msg


def _make_bridge():
    """Create a DiscordBridge without calling __init__ (avoids env/boto deps)."""
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = "https://sqs.us-east-1.amazonaws.com/123/test-queue"
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None

    # Minimal discord client mock
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    bridge.client.user.mentioned_in = MagicMock(return_value=False)

    return bridge


# ===========================================================================
# TestMakeEventDetail
# ===========================================================================


class TestMakeMessagePayload:
    def test_basic_fields(self):
        msg = _make_message(content="hi there", channel_id=100, guild_id=200, message_id=300)
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["content"] == "hi there"
        assert detail["channel_id"] == "100"
        assert detail["guild_id"] == "200"
        assert detail["message_id"] == "300"
        assert detail["message_type"] == "discord:channel.message"
        assert detail["is_dm"] is False
        assert detail["is_mention"] is False

    def test_dm_fields(self):
        msg = _make_message(is_dm=True, channel_id=101, message_id=301)
        detail = _make_message_payload(msg, "discord:dm", is_dm=True, is_mention=False)

        assert detail["guild_id"] is None
        assert detail["is_dm"] is True

    def test_attachment_metadata(self):
        att = MagicMock()
        att.url = "https://cdn.discord.com/img.png"
        att.filename = "img.png"
        att.content_type = "image/png"
        att.size = 1024
        att.width = 800
        att.height = 600

        msg = _make_message(attachments=[att])
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        atts = detail["attachments"]
        assert len(atts) == 1
        assert atts[0]["url"] == "https://cdn.discord.com/img.png"
        assert atts[0]["is_image"] is True
        assert atts[0]["width"] == 800
        assert atts[0]["height"] == 600

    def test_attachment_non_image(self):
        att = MagicMock()
        att.url = "https://cdn.discord.com/file.txt"
        att.filename = "file.txt"
        att.content_type = "text/plain"
        att.size = 256
        att.width = None
        att.height = None

        msg = _make_message(attachments=[att])
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["attachments"][0]["is_image"] is False

    def test_attachment_no_content_type(self):
        att = MagicMock()
        att.url = "https://cdn.discord.com/file.bin"
        att.filename = "file.bin"
        att.content_type = None
        att.size = 512
        att.width = None
        att.height = None

        msg = _make_message(attachments=[att])
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["attachments"][0]["is_image"] is False

    def test_thread_context(self):
        msg = _make_message(is_thread=True, channel_id=500, parent_channel_id=400)
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["thread_id"] == "500"
        assert detail["parent_channel_id"] == "400"

    def test_embed_metadata(self):
        embed = MagicMock(spec=discord.Embed)
        embed.type = "rich"
        embed.title = "Title"
        embed.description = "Desc"
        embed.url = "https://example.com"
        embed.image = MagicMock()
        embed.image.url = "https://example.com/img.png"

        msg = _make_message(embeds=[embed])
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        embeds = detail["embeds"]
        assert len(embeds) == 1
        assert embeds[0]["title"] == "Title"
        assert embeds[0]["image_url"] == "https://example.com/img.png"

    def test_reference_message_id(self):
        ref = MagicMock()
        ref.message_id = 12345

        msg = _make_message(reference=ref)
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["reference_message_id"] == "12345"

    def test_no_reference(self):
        msg = _make_message(reference=None)
        detail = _make_message_payload(msg, "discord:channel.message", is_dm=False, is_mention=False)

        assert detail["reference_message_id"] is None


# ===========================================================================
# TestBridgeInbound
# ===========================================================================


class TestBridgeInbound:
    async def test_relay_channel_message(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="hi")
        await bridge._relay_to_db(msg)

        repo.append_channel_message.assert_called_once()
        channel_msg = repo.append_channel_message.call_args.args[0]
        assert channel_msg.payload["message_type"] == "discord:message"

    async def test_relay_dm(self):
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(is_dm=True, content="secret")
        await bridge._relay_to_db(msg)

        repo.append_channel_message.assert_called_once()
        channel_msg = repo.append_channel_message.call_args.args[0]
        assert channel_msg.payload["is_dm"] is True
        assert channel_msg.payload["message_type"] == "discord:dm"

    async def test_relay_mention(self):
        bridge = _make_bridge()
        bridge.client.user.mentioned_in.return_value = True
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:mention", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="@bot hey")
        await bridge._relay_to_db(msg)

        channel_msg = repo.append_channel_message.call_args.args[0]
        assert channel_msg.payload["message_type"] == "discord:mention"

    async def test_relay_starts_typing_on_dm(self):
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(is_dm=True)
        await bridge._relay_to_db(msg)

        bridge._start_typing.assert_called_once_with(msg.channel)

    async def test_relay_starts_typing_on_mention(self):
        bridge = _make_bridge()
        bridge.client.user.mentioned_in.return_value = True
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:mention", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="@bot yo")
        await bridge._relay_to_db(msg)

        bridge._start_typing.assert_called_once()

    async def test_relay_no_typing_on_channel_message(self):
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType
        ch = Channel(name="io:discord:message", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="just chatting")
        await bridge._relay_to_db(msg)

        bridge._start_typing.assert_not_called()


# ===========================================================================
# TestBridgeOutbound
# ===========================================================================


class TestBridgeOutbound:
    async def test_handle_message_sends_content(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        await bridge._handle_message({"content": "hello world"}, channel)

        channel.send.assert_called_once()
        args, kwargs = channel.send.call_args
        assert args[0] == "hello world"

    async def test_handle_message_chunks_long_content(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        long_content = "a" * 3000
        await bridge._handle_message({"content": long_content}, channel)

        assert channel.send.call_count == 2

    async def test_handle_reaction(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100
        mock_message = AsyncMock()
        channel.fetch_message.return_value = mock_message

        await bridge._handle_reaction(
            {"message_id": "456", "emoji": "\U0001f44d"},
            channel,
        )

        channel.fetch_message.assert_called_once_with(456)
        mock_message.add_reaction.assert_called_once_with("\U0001f44d")

    async def test_handle_reaction_missing_fields(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        # Missing emoji should not attempt fetch
        await bridge._handle_reaction({"message_id": "456"}, channel)
        channel.fetch_message.assert_not_called()

    async def test_handle_dm(self):
        bridge = _make_bridge()
        bridge._stop_typing = MagicMock()
        mock_user = AsyncMock()
        mock_dm_channel = AsyncMock()
        mock_dm_channel.id = 444
        mock_user.create_dm.return_value = mock_dm_channel
        bridge.client.fetch_user = AsyncMock(return_value=mock_user)

        await bridge._handle_dm({"user_id": "777", "content": "hi there"})

        bridge.client.fetch_user.assert_called_once_with(777)
        mock_user.create_dm.assert_called_once()
        bridge._stop_typing.assert_called_once_with(444)
        mock_dm_channel.send.assert_called_once_with("hi there")

    async def test_handle_thread_create_on_message(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100
        mock_message = AsyncMock()
        mock_thread = AsyncMock()
        channel.fetch_message.return_value = mock_message
        mock_message.create_thread.return_value = mock_thread

        await bridge._handle_thread_create(
            {"thread_name": "Discussion", "message_id": "456", "content": "Let's talk"},
            channel,
        )

        channel.fetch_message.assert_called_once_with(456)
        mock_message.create_thread.assert_called_once_with(name="Discussion")
        mock_thread.send.assert_called_once_with("Let's talk")

    async def test_handle_message_with_reply_to(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        await bridge._handle_message(
            {"content": "reply text", "reply_to": "789"},
            channel,
        )

        _, kwargs = channel.send.call_args
        assert kwargs["reference"] is not None
        assert kwargs["reference"].message_id == 789

    async def test_handle_message_with_files(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100
        bridge._download_files = AsyncMock(return_value=[MagicMock(spec=discord.File)])

        await bridge._handle_message(
            {"content": "see file", "files": [{"url": "https://example.com/f.png", "filename": "f.png"}]},
            channel,
        )

        bridge._download_files.assert_called_once()
        _, kwargs = channel.send.call_args
        assert "files" in kwargs
        assert len(kwargs["files"]) == 1

"""Tests for Discord bridge service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from cogos.io.discord.bridge import DiscordBridge, _make_message_payload

# ---------------------------------------------------------------------------
# Helpers to build fake Discord objects
# ---------------------------------------------------------------------------


def _make_author(*, name="testuser", id_=42):
    author = MagicMock()
    author.__str__ = lambda self: name  # type: ignore[assignment]
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
    bridge._s3_client = None
    bridge._blob_bucket = ""
    bridge._pending_dms = {}
    bridge._alerted_dm_ids = set()
    bridge._alert_cooldowns = {}
    bridge._ALERT_COOLDOWN_SECS = 300

    # Multi-tenant routing
    bridge._configs = {"test-bot": MagicMock()}
    bridge._repos = {}
    bridge._sent_message_owners = {}
    bridge._lifecycle = MagicMock()
    bridge._router = MagicMock()
    bridge._router.route.return_value = ["test-bot"]
    bridge._router.available_cogents.return_value = ["test-bot"]

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

        # 2 writes: catch-all + fine-grained channel
        assert repo.append_channel_message.call_count == 2
        channel_msg = repo.append_channel_message.call_args_list[0].args[0]
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

        # 2 writes: catch-all + fine-grained channel
        assert repo.append_channel_message.call_count == 2
        channel_msg = repo.append_channel_message.call_args_list[0].args[0]
        assert channel_msg.payload["is_dm"] is True
        assert channel_msg.payload["message_type"] == "discord:dm"

    async def test_relay_mention(self):
        bridge = _make_bridge()
        bridge.client.user.mentioned_in.return_value = True  # type: ignore[attr-defined]
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        ch = Channel(name="io:discord:mention", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="@bot hey")
        await bridge._relay_to_db(msg)

        # Mentions should only write to the catch-all channel, not a fine-grained one
        assert repo.append_channel_message.call_count == 1
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
        bridge.client.user.mentioned_in.return_value = True  # type: ignore[attr-defined]
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        ch = Channel(name="io:discord:mention", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(content="@bot yo")
        await bridge._relay_to_db(msg)

        bridge._start_typing.assert_called_once()

    async def test_relay_channel_message_writes_to_fine_grained_channel(self):
        """Channel messages should also write to io:discord:test-bot:message:<channel_id>."""
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        catch_all = Channel(name="io:discord:test-bot:message", channel_type=ChannelType.NAMED)
        fine = Channel(name="io:discord:test-bot:message:100", channel_type=ChannelType.NAMED)

        def _get_channel(name):
            if name == "io:discord:test-bot:message":
                return catch_all
            if name == "io:discord:test-bot:message:100":
                return fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(content="hi", channel_id=100)
        await bridge._relay_to_db(msg)

        assert repo.append_channel_message.call_count == 2
        channels_written = {call.args[0].channel for call in repo.append_channel_message.call_args_list}
        assert catch_all.id in channels_written
        assert fine.id in channels_written

    async def test_relay_dm_writes_to_fine_grained_channel(self):
        """DM messages should also write to io:discord:test-bot:dm:<author_id>."""
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        catch_all = Channel(name="io:discord:test-bot:dm", channel_type=ChannelType.NAMED)
        fine = Channel(name="io:discord:test-bot:dm:42", channel_type=ChannelType.NAMED)

        def _get_channel(name):
            if name == "io:discord:test-bot:dm":
                return catch_all
            if name == "io:discord:test-bot:dm:42":
                return fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(is_dm=True, content="secret")
        await bridge._relay_to_db(msg)

        assert repo.append_channel_message.call_count == 2
        channels_written = {call.args[0].channel for call in repo.append_channel_message.call_args_list}
        assert catch_all.id in channels_written
        assert fine.id in channels_written

    async def test_relay_creates_fine_grained_channel_if_missing(self):
        """Fine-grained channel should be auto-created if it doesn't exist."""
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        catch_all = Channel(name="io:discord:test-bot:message", channel_type=ChannelType.NAMED)
        created_fine = Channel(name="io:discord:test-bot:message:100", channel_type=ChannelType.NAMED)

        call_count = {"fine": 0}

        def _get_channel(name):
            if name == "io:discord:test-bot:message":
                return catch_all
            if name == "io:discord:test-bot:message:100":
                call_count["fine"] += 1
                return None if call_count["fine"] == 1 else created_fine
            return None

        repo.get_channel_by_name.side_effect = _get_channel

        msg = _make_message(content="hi", channel_id=100)
        await bridge._relay_to_db(msg)

        # Should have upserted the fine-grained channel
        upsert_calls = [
            c for c in repo.upsert_channel.call_args_list
            if c.args[0].name == "io:discord:test-bot:message:100"
        ]
        assert len(upsert_calls) == 1
        assert repo.append_channel_message.call_count == 2

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

    async def test_handle_message_converts_markdown(self):
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        await bridge._handle_message(
            {"content": "# Hello\n\n[link](https://example.com)"},
            channel,
        )

        args, kwargs = channel.send.call_args
        sent = args[0]
        assert "**Hello**" in sent
        assert "link (<https://example.com>)" in sent
        assert "# Hello" not in sent

    async def test_handle_dm_propagates_exception(self):
        """DM send failures should propagate so SQS can retry."""
        bridge = _make_bridge()
        bridge._stop_typing = MagicMock()
        bridge.client.fetch_user = AsyncMock(side_effect=RuntimeError("Discord API down"))

        with pytest.raises(RuntimeError, match="Discord API down"):
            await bridge._handle_dm({"user_id": "777", "content": "hi"})

    async def test_handle_reaction_propagates_exception(self):
        """Reaction failures should propagate so SQS can retry."""
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100
        channel.fetch_message.side_effect = RuntimeError("not found")

        with pytest.raises(RuntimeError):
            await bridge._handle_reaction({"message_id": "456", "emoji": "👍"}, channel)

    async def test_handle_thread_create_propagates_exception(self):
        """Thread create failures should propagate so SQS can retry."""
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100
        channel.fetch_message.side_effect = RuntimeError("not found")

        with pytest.raises(RuntimeError):
            await bridge._handle_thread_create({"thread_name": "T", "message_id": "456", "content": "hi"}, channel)

    async def test_handle_dm_clears_pending(self):
        """Successful DM send should clear the pending DM tracker."""
        bridge = _make_bridge()
        bridge._stop_typing = MagicMock()
        mock_user = AsyncMock()
        mock_dm_channel = AsyncMock()
        mock_dm_channel.id = 444
        mock_user.create_dm.return_value = mock_dm_channel
        bridge.client.fetch_user = AsyncMock(return_value=mock_user)

        # Simulate a pending DM for this channel
        bridge._pending_dms["444"] = ("msg123", "777", 1000.0, "test-bot")

        await bridge._handle_dm({"user_id": "777", "content": "reply"})

        assert "444" not in bridge._pending_dms

    async def test_handle_message_clears_pending_dm(self):
        """Message sent to a DM channel should clear pending DM tracker."""
        bridge = _make_bridge()
        channel = AsyncMock()
        channel.id = 100

        bridge._pending_dms["555"] = ("msg456", "42", 1000.0, "test-bot")

        await bridge._handle_message({"content": "reply", "channel": "555"}, channel)

        assert "555" not in bridge._pending_dms


# ===========================================================================
# TestAlertingAndTimeout
# ===========================================================================


class TestAlertingAndTimeout:
    async def test_relay_dm_tracks_pending(self):
        """Inbound DM should be tracked as pending."""
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        from cogos.db.models import Channel, ChannelType

        ch = Channel(name="io:discord:dm", channel_type=ChannelType.NAMED)
        repo.get_channel_by_name.return_value = ch

        msg = _make_message(is_dm=True, content="hello", channel_id=101, message_id=301)
        await bridge._relay_to_db(msg)

        assert "101" in bridge._pending_dms
        msg_id, author_id, _, cogent = bridge._pending_dms["101"]
        assert msg_id == "301"
        assert author_id == "42"
        assert cogent == "test-bot"

    async def test_relay_dm_failure_creates_alert(self):
        """Failed inbound DM relay should create a critical alert."""
        bridge = _make_bridge()
        bridge._start_typing = MagicMock()
        bridge._create_alert = MagicMock()
        repo = MagicMock()
        repo.get_channel_by_name.return_value = None  # force channel lookup to return None
        bridge._get_repo = MagicMock(return_value=repo)

        # _get_or_create_channel returns None → raises RuntimeError
        msg = _make_message(is_dm=True, content="hello")
        await bridge._relay_to_db(msg)

        bridge._create_alert.assert_called_once()
        call_args = bridge._create_alert.call_args
        assert call_args.args[0] == "test-bot"
        assert call_args.args[1] == "critical"
        assert call_args.args[2] == "discord:inbound_relay_failed"

    async def test_relay_channel_message_failure_no_alert(self):
        """Failed relay for regular channel messages should NOT create an alert."""
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()
        repo = MagicMock()
        repo.get_channel_by_name.return_value = None
        bridge._get_repo = MagicMock(return_value=repo)

        msg = _make_message(content="hello")
        await bridge._relay_to_db(msg)

        bridge._create_alert.assert_not_called()

    async def test_poll_replies_discards_on_forbidden(self):
        """Forbidden errors (permanent) should discard the message and alert."""
        bridge = _make_bridge()
        bridge._alert_reply_failure = MagicMock()

        sqs_msg = {
            "MessageId": "sqs-1",
            "ReceiptHandle": "rh-1",
            "Body": json.dumps(
                {
                    "type": "dm",
                    "user_id": "777",
                    "content": "hi",
                    "_meta": {"process_id": "p1", "trace_id": "t1"},
                }
            ),
        }

        resp = MagicMock()
        resp.status = 403
        bridge._send_reply = AsyncMock(side_effect=discord.errors.Forbidden(resp, "Cannot send messages to this user"))
        bridge._sqs_client.receive_message.return_value = {"Messages": [sqs_msg]}

        await bridge._poll_replies(_max_iterations=1)

        bridge._alert_reply_failure.assert_called_once()
        call_kwargs = bridge._alert_reply_failure.call_args
        assert call_kwargs.kwargs["permanent"] is True
        # SQS message SHOULD be deleted (permanent failure, no retry)
        bridge._sqs_client.delete_message.assert_called_once()

    async def test_poll_replies_discards_on_invalid_channel_id(self):
        """ValueError from invalid channel IDs should discard the message and alert."""
        bridge = _make_bridge()
        bridge._alert_reply_failure = MagicMock()

        sqs_msg = {
            "MessageId": "sqs-1",
            "ReceiptHandle": "rh-1",
            "Body": json.dumps(
                {
                    "type": "message",
                    "channel": "fake-dm-channel-999",
                    "content": "hi",
                    "_meta": {"process_id": "p1", "trace_id": "t1"},
                }
            ),
        }

        bridge._send_reply = AsyncMock(
            side_effect=ValueError("invalid literal for int() with base 10: 'fake-dm-channel-999'")
        )
        bridge._sqs_client.receive_message.return_value = {"Messages": [sqs_msg]}

        await bridge._poll_replies(_max_iterations=1)

        bridge._alert_reply_failure.assert_called_once()
        call_kwargs = bridge._alert_reply_failure.call_args
        assert call_kwargs.kwargs["permanent"] is True
        # SQS message SHOULD be deleted (permanent failure, no retry)
        bridge._sqs_client.delete_message.assert_called_once()

    async def test_poll_replies_alerts_on_send_failure(self):
        """SQS reply send failure should alert and leave message for retry."""
        bridge = _make_bridge()
        bridge._alert_reply_failure = MagicMock()

        sqs_msg = {
            "MessageId": "sqs-1",
            "ReceiptHandle": "rh-1",
            "Body": json.dumps({
                "type": "dm",
                "user_id": "777",
                "content": "hi",
                "_meta": {"process_id": "p1", "trace_id": "t1"},
            }),
        }

        bridge._send_reply = AsyncMock(side_effect=RuntimeError("boom"))
        bridge._sqs_client.receive_message.return_value = {"Messages": [sqs_msg]}

        await bridge._poll_replies(_max_iterations=1)

        bridge._alert_reply_failure.assert_called_once()
        call_kwargs = bridge._alert_reply_failure.call_args
        assert call_kwargs.kwargs["permanent"] is False
        # SQS message should NOT be deleted (for retry)
        bridge._sqs_client.delete_message.assert_not_called()

    def test_alert_reply_failure_creates_alert(self, caplog):
        """_alert_reply_failure should call _create_alert with correct severity."""
        import logging
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()
        # Reset cooldowns between calls since they share the same bridge
        object.__setattr__(bridge, "_ALERT_COOLDOWN_SECS", 0)

        msg = {
            "MessageId": "sqs-1",
            "Body": json.dumps({
                "type": "dm",
                "_meta": {"process_id": "p1", "cogent_name": "test-bot"},
            }),
        }

        with caplog.at_level(logging.DEBUG):
            bridge._alert_reply_failure(msg, RuntimeError("boom"), permanent=False)

        assert bridge._create_alert.call_count == 1, (
            f"Expected 1 call, got {bridge._create_alert.call_count}. Logs: {caplog.text}"
        )
        assert bridge._create_alert.call_args.args[1] == "critical"
        assert bridge._create_alert.call_args.args[2] == "discord:send_failed"

        bridge._create_alert.reset_mock()
        with caplog.at_level(logging.DEBUG):
            bridge._alert_reply_failure(
                msg, discord.errors.Forbidden(MagicMock(status=403), "no"), permanent=True,
            )

        assert bridge._create_alert.call_count == 1, (
            f"Expected 1 call, got {bridge._create_alert.call_count}. Logs: {caplog.text}"
        )
        assert bridge._create_alert.call_args.args[1] == "warning"
        assert bridge._create_alert.call_args.args[2] == "discord:send_permanent_failure"

    async def test_poll_replies_deletes_on_success(self):
        """Successful send should delete the SQS message."""
        bridge = _make_bridge()

        sqs_msg = {
            "MessageId": "sqs-1",
            "ReceiptHandle": "rh-1",
            "Body": json.dumps({"type": "message", "channel": "100", "content": "hi"}),
        }

        bridge._send_reply = AsyncMock()
        bridge._sqs_client.receive_message.return_value = {"Messages": [sqs_msg]}

        await bridge._poll_replies(_max_iterations=1)

        bridge._sqs_client.delete_message.assert_called_once()

    def test_pending_dm_tracking(self):
        """Basic pending DM track/clear cycle."""
        bridge = _make_bridge()

        bridge._track_pending_dm("ch1", "msg1", "user1", "test-bot")
        assert "ch1" in bridge._pending_dms

        bridge._clear_pending_dm("ch1")
        assert "ch1" not in bridge._pending_dms

    def test_clear_pending_dm_noop_if_missing(self):
        """Clearing a non-existent pending DM should not raise."""
        bridge = _make_bridge()
        bridge._clear_pending_dm("nonexistent")  # should not raise

    def test_create_alert_helper(self):
        """_create_alert should call repo.create_alert."""
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        bridge._create_alert("test-bot", "warning", "test:alert", "something happened", {"key": "val"})

        repo.create_alert.assert_called_once_with(
            severity="warning",
            alert_type="test:alert",
            source="discord:bridge:test-bot",
            message="something happened",
            metadata={"key": "val"},
        )

    def test_create_alert_swallows_errors(self):
        """_create_alert should never raise, even if repo fails."""
        bridge = _make_bridge()
        repo = MagicMock()
        repo.create_alert.side_effect = RuntimeError("db down")
        bridge._get_repo = MagicMock(return_value=repo)

        # Should not raise
        bridge._create_alert("test-bot", "critical", "test:alert", "boom", {})

    def test_sweep_alerts_on_timeout(self):
        """_sweep_pending_dms should alert when DM exceeds timeout."""
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()

        # Simulate a DM received 6 minutes ago (> 300s timeout)
        import time as _time

        bridge._pending_dms["ch1"] = ("msg1", "user1", _time.time() - 360, "test-bot")

        bridge._sweep_pending_dms()

        bridge._create_alert.assert_called_once()
        assert bridge._create_alert.call_args.args[0] == "test-bot"
        assert bridge._create_alert.call_args.args[2] == "discord:dm_timeout"
        assert "msg1" in bridge._alerted_dm_ids

    def test_sweep_does_not_double_alert(self):
        """_sweep_pending_dms should only alert once per message."""
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()

        import time as _time

        bridge._pending_dms["ch1"] = ("msg1", "user1", _time.time() - 360, "test-bot")

        bridge._sweep_pending_dms()
        bridge._sweep_pending_dms()  # second sweep

        # Only alerted once
        bridge._create_alert.assert_called_once()

    def test_sweep_skips_fresh_dms(self):
        """_sweep_pending_dms should not alert for recent DMs."""
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()

        import time as _time

        bridge._pending_dms["ch1"] = ("msg1", "user1", _time.time() - 10, "test-bot")  # 10s ago

        bridge._sweep_pending_dms()

        bridge._create_alert.assert_not_called()
        assert "ch1" in bridge._pending_dms  # still tracked

    def test_sweep_cleans_stale_entries(self):
        """_sweep_pending_dms should remove entries older than 1 hour."""
        bridge = _make_bridge()
        bridge._create_alert = MagicMock()

        import time as _time

        bridge._pending_dms["ch1"] = ("msg1", "user1", _time.time() - 4000, "test-bot")  # >1h ago
        bridge._alerted_dm_ids.add("msg1")

        bridge._sweep_pending_dms()

        assert "ch1" not in bridge._pending_dms
        assert "msg1" not in bridge._alerted_dm_ids

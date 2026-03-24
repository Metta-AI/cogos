"""Tests for Discord bridge reaction relay."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import discord
import pytest

from cogos.db.sqlite_repository import SqliteRepository
from cogos.db.models import Channel, ChannelType
from cogos.io.discord.bridge import DiscordBridge


def _make_bridge() -> DiscordBridge:
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999  # bot's own user ID
    bridge._typing_tasks = {}
    bridge._s3_client = None
    bridge._blob_bucket = ""
    bridge._sent_message_owners = {}
    bridge._repos = {}
    bridge._configs = {}
    bridge._lifecycle = MagicMock()
    bridge._lifecycle.personas = {}
    return bridge


@pytest.mark.anyio
async def test_relay_reaction_on_own_message():
    """Bridge relays reactions on bot's own messages to all cogents."""
    bridge = _make_bridge()
    bridge._configs = {"test-cogent": MagicMock()}

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    reaction_channel = Channel(name="io:discord:test-cogent:reaction", channel_type=ChannelType.NAMED)
    repo.get_channel_by_name.return_value = reaction_channel

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "\U0001f44d"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 999  # bot's own message
    mock_message.webhook_id = None
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.get_channel = MagicMock(return_value=None)
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    repo.append_channel_message.assert_called_once()
    msg = repo.append_channel_message.call_args.args[0]
    assert msg.payload["message_id"] == "12345"
    assert msg.payload["reactor_id"] == "11111"
    assert msg.payload["emoji"] == "\U0001f44d"
    assert msg.payload["channel_id"] == "67890"


@pytest.mark.anyio
async def test_ignores_reaction_on_others_message():
    """Bridge ignores reactions on messages NOT authored by the bot or webhooks."""
    bridge = _make_bridge()
    bridge._configs = {"test-cogent": MagicMock()}

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "\U0001f44d"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 88888  # NOT the bot
    mock_message.webhook_id = None
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.get_channel = MagicMock(return_value=None)
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    repo.append_channel_message.assert_not_called()


@pytest.mark.anyio
async def test_ignores_bot_reactions():
    """Bridge ignores reactions from bots."""
    bridge = _make_bridge()

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 999  # bot reacting to itself
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "\U0001f4cb"
    raw_event.member = MagicMock()
    raw_event.member.bot = True

    await bridge._on_raw_reaction_add(raw_event)

    repo.append_channel_message.assert_not_called()


@pytest.mark.anyio
async def test_creates_reaction_channel_if_missing():
    """Bridge creates scoped reaction channel if it doesn't exist."""
    bridge = _make_bridge()
    bridge._configs = {"test-cogent": MagicMock()}

    repo = MagicMock()
    bridge._get_repo = MagicMock(return_value=repo)

    created_channel = Channel(name="io:discord:test-cogent:reaction", channel_type=ChannelType.NAMED)
    call_count = [0]

    def _get_channel(name):
        call_count[0] += 1
        if "reaction" in name:
            return None if call_count[0] == 1 else created_channel
        return None

    repo.get_channel_by_name.side_effect = _get_channel

    raw_event = MagicMock(spec=discord.RawReactionActionEvent)
    raw_event.message_id = 12345
    raw_event.channel_id = 67890
    raw_event.user_id = 11111
    raw_event.guild_id = 22222
    raw_event.emoji = MagicMock()
    raw_event.emoji.name = "\U0001f44d"
    raw_event.member = MagicMock()
    raw_event.member.bot = False

    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.author.id = 999  # bot's own message
    mock_message.webhook_id = None
    mock_channel.fetch_message.return_value = mock_message
    bridge.client.get_channel = MagicMock(return_value=None)
    bridge.client.fetch_channel = AsyncMock(return_value=mock_channel)

    await bridge._on_raw_reaction_add(raw_event)

    repo.upsert_channel.assert_called_once()
    repo.append_channel_message.assert_called_once()

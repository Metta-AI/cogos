"""Tests for Discord bridge guild/channel sync."""

from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest

from cogos.io.discord.bridge import DiscordBridge


def _make_bridge():
    bridge = DiscordBridge.__new__(DiscordBridge)
    bridge.cogent_name = "test-bot"
    bridge.bot_token = "fake-token"
    bridge.reply_queue_url = ""
    bridge.region = "us-east-1"
    bridge._sqs_client = MagicMock()
    bridge._typing_tasks = {}
    bridge._repo = None
    bridge.client = MagicMock()
    bridge.client.user = MagicMock()
    bridge.client.user.id = 999
    bridge.client.user.mentioned_in = MagicMock(return_value=False)
    return bridge


def _make_text_channel(*, channel_id=200, name="general", topic=None, category_name=None, position=0):
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = channel_id
    ch.name = name
    ch.topic = topic
    ch.position = position
    ch.type = discord.ChannelType.text
    if category_name:
        cat = MagicMock()
        cat.name = category_name
        ch.category = cat
    else:
        ch.category = None
    return ch


class TestGuildSync:
    @pytest.mark.asyncio
    async def test_sync_guild_writes_to_repo(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        ch1 = _make_text_channel(channel_id=201, name="general", topic="Chat here")
        ch2 = _make_text_channel(channel_id=202, name="dev", category_name="Engineering")
        guild = MagicMock(spec=discord.Guild)
        guild.id = 100
        guild.name = "My Server"
        guild.icon = MagicMock()
        guild.icon.url = "https://cdn.discord.com/icons/100/abc.png"
        guild.member_count = 10
        guild.channels = [ch1, ch2]

        await bridge._sync_guild(guild)

        repo.upsert_discord_guild.assert_called_once()
        g = repo.upsert_discord_guild.call_args.args[0]
        assert g.guild_id == "100"
        assert g.name == "My Server"
        assert repo.upsert_discord_channel.call_count == 2

    @pytest.mark.asyncio
    async def test_on_channel_delete_removes_from_repo(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        ch = _make_text_channel(channel_id=201, name="deleted")
        await bridge._on_channel_delete(ch)

        repo.delete_discord_channel.assert_called_once_with("201")

    @pytest.mark.asyncio
    async def test_sync_guild_no_icon(self):
        bridge = _make_bridge()
        repo = MagicMock()
        bridge._get_repo = MagicMock(return_value=repo)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 100
        guild.name = "No Icon"
        guild.icon = None
        guild.member_count = 5
        guild.channels = []

        await bridge._sync_guild(guild)

        g = repo.upsert_discord_guild.call_args.args[0]
        assert g.icon_url is None

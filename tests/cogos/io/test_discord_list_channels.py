"""Tests for DiscordCapability list_channels/list_guilds."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.io.discord.capability import DiscordCapability


def _make_cap(repo=None):
    repo = repo or MagicMock()
    return DiscordCapability(repo, uuid4())


def test_list_guilds():
    repo = MagicMock()
    repo.list_discord_guilds.return_value = [
        DiscordGuild(guild_id="1", cogent_name="alpha", name="Server A"),
        DiscordGuild(guild_id="2", cogent_name="alpha", name="Server B"),
    ]
    cap = _make_cap(repo)
    guilds = cap.list_guilds()
    assert len(guilds) == 2
    assert guilds[0].guild_id == "1"


def test_list_channels():
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
        DiscordChannel(channel_id="11", guild_id="1", name="random", channel_type="text"),
    ]
    cap = _make_cap(repo)
    channels = cap.list_channels(guild_id="1")
    assert len(channels) == 2
    repo.list_discord_channels.assert_called_once_with(guild_id="1")


def test_list_channels_scoped():
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
        DiscordChannel(channel_id="11", guild_id="1", name="secret", channel_type="text"),
    ]
    cap = _make_cap(repo)
    scoped = cap.scope(channels=["10"])
    channels = scoped.list_channels()
    assert len(channels) == 1
    assert channels[0].channel_id == "10"


def test_list_channels_no_scope_returns_all():
    repo = MagicMock()
    repo.list_discord_channels.return_value = [
        DiscordChannel(channel_id="10", guild_id="1", name="general", channel_type="text"),
    ]
    cap = _make_cap(repo)
    channels = cap.list_channels()
    assert len(channels) == 1


def test_send_converts_blob_keys_to_file_specs():
    """send() with blob key strings should convert to s3_key dicts."""
    from unittest.mock import patch

    cap = _make_cap()
    # Mock _send_sqs to capture the body
    with patch("cogos.io.discord.capability._send_sqs") as mock_sqs:
        cap.send("123", "hello", files=["blobs/abc/chart.png"])

    body = mock_sqs.call_args.args[0]
    assert body["files"] == [{"s3_key": "blobs/abc/chart.png", "filename": "chart.png"}]


def test_send_passes_dict_files_through():
    """send() with dict files should pass them through unchanged."""
    from unittest.mock import patch

    cap = _make_cap()
    with patch("cogos.io.discord.capability._send_sqs") as mock_sqs:
        cap.send("123", "hello", files=[{"url": "https://example.com/f.png", "filename": "f.png"}])

    body = mock_sqs.call_args.args[0]
    assert body["files"] == [{"url": "https://example.com/f.png", "filename": "f.png"}]

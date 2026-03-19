"""Tests for Discord metadata repository methods."""

from cogos.db.local_repository import LocalRepository
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild


def test_upsert_and_get_guild(tmp_path):
    repo = LocalRepository(str(tmp_path))
    guild = DiscordGuild(guild_id="123", cogent_name="alpha", name="Test Server")
    repo.upsert_discord_guild(guild)
    result = repo.get_discord_guild("123")
    assert result is not None
    assert result.name == "Test Server"


def test_upsert_guild_updates(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_guild(DiscordGuild(guild_id="123", cogent_name="alpha", name="Old Name"))
    repo.upsert_discord_guild(DiscordGuild(guild_id="123", cogent_name="alpha", name="New Name"))
    result = repo.get_discord_guild("123")
    assert result is not None
    assert result.name == "New Name"


def test_list_discord_guilds(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_guild(DiscordGuild(guild_id="1", cogent_name="alpha", name="A"))
    repo.upsert_discord_guild(DiscordGuild(guild_id="2", cogent_name="alpha", name="B"))
    guilds = repo.list_discord_guilds("alpha")
    assert len(guilds) == 2


def test_upsert_and_get_discord_channel(tmp_path):
    repo = LocalRepository(str(tmp_path))
    ch = DiscordChannel(channel_id="789", guild_id="123", name="general", channel_type="text")
    repo.upsert_discord_channel(ch)
    result = repo.get_discord_channel("789")
    assert result is not None
    assert result.name == "general"


def test_list_discord_channels(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="2", guild_id="123", name="random", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="3", guild_id="456", name="other", channel_type="text"))
    channels = repo.list_discord_channels(guild_id="123")
    assert len(channels) == 2
    names = {ch.name for ch in channels}
    assert names == {"general", "random"}


def test_list_discord_channels_all(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="a", channel_type="text"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="2", guild_id="456", name="b", channel_type="text"))
    channels = repo.list_discord_channels()
    assert len(channels) == 2


def test_delete_discord_channel(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))
    repo.delete_discord_channel("1")
    assert repo.get_discord_channel("1") is None


def test_delete_discord_guild_cascades(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_discord_guild(DiscordGuild(guild_id="123", cogent_name="alpha", name="Server"))
    repo.upsert_discord_channel(DiscordChannel(channel_id="1", guild_id="123", name="general", channel_type="text"))
    repo.delete_discord_guild("123")
    assert repo.get_discord_guild("123") is None
    assert repo.get_discord_channel("1") is None

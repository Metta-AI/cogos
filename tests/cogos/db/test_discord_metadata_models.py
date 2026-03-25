"""Tests for DiscordGuild and DiscordChannel models."""

from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild


def test_discord_guild_basic():
    g = DiscordGuild(guild_id="123456", cogent_name="alpha", name="My Server")
    assert g.guild_id == "123456"
    assert g.cogent_name == "alpha"
    assert g.name == "My Server"
    assert g.icon_url is None
    assert g.member_count is None


def test_discord_guild_full():
    g = DiscordGuild(
        guild_id="123456",
        cogent_name="alpha",
        name="My Server",
        icon_url="https://cdn.discord.com/icons/123/abc.png",
        member_count=42,
    )
    assert g.icon_url == "https://cdn.discord.com/icons/123/abc.png"
    assert g.member_count == 42


def test_discord_channel_basic():
    ch = DiscordChannel(
        channel_id="789",
        guild_id="123456",
        name="general",
        channel_type="text",
        position=0,
    )
    assert ch.channel_id == "789"
    assert ch.guild_id == "123456"
    assert ch.name == "general"
    assert ch.topic is None
    assert ch.category is None
    assert ch.channel_type == "text"
    assert ch.position == 0


def test_discord_channel_full():
    ch = DiscordChannel(
        channel_id="789",
        guild_id="123456",
        name="dev-talk",
        topic="Development discussion",
        category="Engineering",
        channel_type="text",
        position=3,
    )
    assert ch.topic == "Development discussion"
    assert ch.category == "Engineering"

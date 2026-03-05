"""Verify all channels can be imported and instantiated."""

from channels.base import Channel, ChannelMode, InboundEvent
from channels.discord import DiscordChannel
from channels.github import GitHubChannel
from channels.gmail import GmailChannel
from channels.asana import AsanaChannel
from channels.calendar import CalendarChannel


class TestAllChannelsImport:
    def test_discord(self):
        ch = DiscordChannel()
        assert ch.mode == ChannelMode.LIVE
        assert isinstance(ch, Channel)

    def test_github(self):
        ch = GitHubChannel()
        assert ch.mode == ChannelMode.ON_DEMAND
        assert isinstance(ch, Channel)

    def test_gmail(self):
        ch = GmailChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_asana(self):
        ch = AsanaChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

    def test_calendar(self):
        ch = CalendarChannel()
        assert ch.mode == ChannelMode.POLL
        assert isinstance(ch, Channel)

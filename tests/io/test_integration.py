"""Verify all channels can be imported and instantiated."""

from cogos.io.base import IOAdapter, IOMode
from cogos.io.github import GitHubIO
from cogos.io.asana import AsanaIO


class TestAllChannelsImport:
    def test_github(self):
        ch = GitHubIO()
        assert ch.mode == IOMode.ON_DEMAND
        assert isinstance(ch, Channel)

    def test_asana(self):
        ch = AsanaIO()
        assert ch.mode == IOMode.POLL
        assert isinstance(ch, Channel)

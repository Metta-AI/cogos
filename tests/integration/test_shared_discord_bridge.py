"""Integration tests for shared Discord bridge modules (lifecycle + router)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock
import discord

from cogos.io.discord.lifecycle import CogentPersona, LifecycleManager, ROLE_PREFIX
from cogos.io.discord.router import MessageRouter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def lifecycle() -> LifecycleManager:
    """LifecycleManager pre-populated with two cogent personas."""
    lm = LifecycleManager()
    lm._personas["alpha"] = CogentPersona(
        cogent_name="alpha",
        display_name="Alpha Bot",
        avatar_url="https://example.com/alpha.png",
        color=0xFF0000,
        default_channels=["100"],
        role_id=9001,
    )
    lm._personas["beta"] = CogentPersona(
        cogent_name="beta",
        display_name="Beta Bot",
        avatar_url="https://example.com/beta.png",
        color=0x00FF00,
        default_channels=["200"],
        role_id=9002,
    )
    return lm


@pytest.fixture
def router(lifecycle: LifecycleManager) -> MessageRouter:
    return MessageRouter(lifecycle)


def _make_role(name: str, role_id: int = 1) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.name = name
    role.id = role_id
    return role


def _make_guild_message(
    *,
    author_id: int = 42,
    channel_id: int = 100,
    role_mentions: list | None = None,
    content: str = "hello",
    is_thread: bool = False,
    thread_id: int | None = None,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content

    author = MagicMock()
    author.id = author_id
    msg.author = author

    if is_thread:
        channel = MagicMock(spec=discord.Thread)
        channel.id = thread_id or channel_id
    else:
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id

    msg.channel = channel
    msg.role_mentions = role_mentions or []
    return msg


def _make_dm_message(
    *,
    author_id: int = 42,
    content: str = "hello",
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content

    author = MagicMock()
    author.id = author_id
    msg.author = author

    channel = MagicMock(spec=discord.DMChannel)
    channel.id = 999
    msg.channel = channel
    msg.role_mentions = []
    return msg


# ---------------------------------------------------------------------------
# 1. Router -- guild message routing
# ---------------------------------------------------------------------------

class TestRouterGuildRouting:
    """Guild message routing: role mentions, threads, channel defaults."""

    def test_role_mention_routes_to_correct_cogent(self, router: MessageRouter):
        role = _make_role(f"{ROLE_PREFIX}alpha", role_id=9001)
        msg = _make_guild_message(role_mentions=[role])

        result = router.route(msg)
        assert result == ["alpha"]

    def test_multiple_role_mentions_route_to_all(self, router: MessageRouter):
        role_a = _make_role(f"{ROLE_PREFIX}alpha", role_id=9001)
        role_b = _make_role(f"{ROLE_PREFIX}beta", role_id=9002)
        msg = _make_guild_message(role_mentions=[role_a, role_b])

        result = router.route(msg)
        assert set(result) == {"alpha", "beta"}

    def test_thread_ownership_routes_to_owner(self, router: MessageRouter):
        thread_id = 555
        router.set_thread_owner(thread_id, "beta")
        msg = _make_guild_message(is_thread=True, thread_id=thread_id)

        result = router.route(msg)
        assert result == ["beta"]

    def test_channel_default_routes_to_default_cogent(self, router: MessageRouter):
        # Channel 100 is the default channel for "alpha"
        msg = _make_guild_message(channel_id=100)

        result = router.route(msg)
        assert result == ["alpha"]

    def test_channel_default_beta(self, router: MessageRouter):
        # Channel 200 is the default channel for "beta"
        msg = _make_guild_message(channel_id=200)

        result = router.route(msg)
        assert result == ["beta"]

    def test_no_match_returns_empty(self, router: MessageRouter):
        # Channel 300 is not a default for any cogent, no role mentions, not a thread
        msg = _make_guild_message(channel_id=300)

        result = router.route(msg)
        assert result == []

    def test_unknown_role_mention_ignored(self, router: MessageRouter):
        role = _make_role(f"{ROLE_PREFIX}unknown", role_id=7777)
        msg = _make_guild_message(role_mentions=[role], channel_id=300)

        result = router.route(msg)
        assert result == []

    def test_non_cogent_role_mention_ignored(self, router: MessageRouter):
        role = _make_role("admin", role_id=1234)
        msg = _make_guild_message(role_mentions=[role], channel_id=300)

        result = router.route(msg)
        assert result == []


# ---------------------------------------------------------------------------
# 2. Router -- DM routing
# ---------------------------------------------------------------------------

class TestRouterDMRouting:
    """DM routing: last interaction, switch intent, @mention switch."""

    def test_dm_with_last_interaction(self, router: MessageRouter):
        router.update_last_interaction(42, "alpha")
        msg = _make_dm_message(author_id=42, content="how are you?")

        result = router.route(msg)
        assert result == ["alpha"]

    def test_dm_switch_intent_updates_mapping(self, router: MessageRouter):
        router.update_last_interaction(42, "alpha")
        msg = _make_dm_message(author_id=42, content="switch to beta")

        result = router.route(msg)
        assert result == ["beta"]

    def test_dm_at_cogent_name_switches(self, router: MessageRouter):
        router.update_last_interaction(42, "alpha")
        msg = _make_dm_message(author_id=42, content="@beta")

        result = router.route(msg)
        assert result == ["beta"]

    def test_dm_bare_cogent_name_switches(self, router: MessageRouter):
        router.update_last_interaction(42, "alpha")
        msg = _make_dm_message(author_id=42, content="beta")

        result = router.route(msg)
        assert result == ["beta"]

    def test_dm_no_prior_interaction_returns_empty(self, router: MessageRouter):
        msg = _make_dm_message(author_id=99, content="hello")

        result = router.route(msg)
        assert result == []

    def test_dm_switch_persists_for_next_message(self, router: MessageRouter):
        # Switch to beta, then send a normal message
        msg1 = _make_dm_message(author_id=42, content="switch to beta")
        router.route(msg1)

        msg2 = _make_dm_message(author_id=42, content="tell me a joke")
        result = router.route(msg2)
        assert result == ["beta"]

    def test_dm_switch_case_insensitive(self, router: MessageRouter):
        msg = _make_dm_message(author_id=42, content="Switch To Alpha")

        result = router.route(msg)
        assert result == ["alpha"]


# ---------------------------------------------------------------------------
# 3. Router -- state tracking
# ---------------------------------------------------------------------------

class TestRouterStateTracking:
    """Verify update_last_interaction, set_thread_owner, and side effects."""

    def test_update_last_interaction_persists(self, router: MessageRouter):
        router.update_last_interaction(1, "alpha")
        assert router._last_interaction[1] == "alpha"

        router.update_last_interaction(1, "beta")
        assert router._last_interaction[1] == "beta"

    def test_set_thread_owner_persists(self, router: MessageRouter):
        router.set_thread_owner(500, "alpha")
        assert router._thread_owners[500] == "alpha"

        router.set_thread_owner(500, "beta")
        assert router._thread_owners[500] == "beta"

    def test_role_mention_updates_last_interaction(self, router: MessageRouter):
        role = _make_role(f"{ROLE_PREFIX}alpha", role_id=9001)
        msg = _make_guild_message(author_id=77, role_mentions=[role])

        router.route(msg)
        assert router._last_interaction[77] == "alpha"

    def test_multiple_role_mentions_last_interaction_set_to_last(self, router: MessageRouter):
        role_a = _make_role(f"{ROLE_PREFIX}alpha", role_id=9001)
        role_b = _make_role(f"{ROLE_PREFIX}beta", role_id=9002)
        msg = _make_guild_message(author_id=77, role_mentions=[role_a, role_b])

        router.route(msg)
        # The last mention in the list wins for last_interaction
        assert router._last_interaction[77] == "beta"

    def test_available_cogents(self, router: MessageRouter):
        names = router.available_cogents()
        assert set(names) == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# 4. Lifecycle -- role naming and persona access
# ---------------------------------------------------------------------------

class TestLifecycleRoleNaming:
    """LifecycleManager.role_name() and get_persona() without Discord API calls."""

    def test_role_name_format(self):
        lm = LifecycleManager()
        assert lm.role_name("alpha") == "cogent:alpha"
        assert lm.role_name("my-bot") == "cogent:my-bot"

    def test_role_name_prefix_matches_constant(self):
        lm = LifecycleManager()
        name = lm.role_name("test")
        assert name.startswith(ROLE_PREFIX)

    def test_get_persona_returns_none_when_missing(self):
        lm = LifecycleManager()
        assert lm.get_persona("nonexistent") is None

    def test_get_persona_returns_persona(self, lifecycle: LifecycleManager):
        persona = lifecycle.get_persona("alpha")
        assert persona is not None
        assert persona.cogent_name == "alpha"
        assert persona.display_name == "Alpha Bot"
        assert persona.role_id == 9001

    def test_personas_property(self, lifecycle: LifecycleManager):
        personas = lifecycle.personas
        assert "alpha" in personas
        assert "beta" in personas
        assert len(personas) == 2

    def test_cogent_persona_defaults(self):
        p = CogentPersona(cogent_name="test")
        assert p.display_name == ""
        assert p.avatar_url == ""
        assert p.color == 0
        assert p.default_channels == []
        assert p.role_id is None
        assert p.webhooks == {}

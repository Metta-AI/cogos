"""Tests for Discord handler pre-processor (history enrichment)."""

import os
from uuid import uuid4

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Channel, ChannelMessage, Process, ProcessMode, ProcessStatus
from cogos.db.models.channel import ChannelType
from cogos.io.discord.preprocessor import enrich_discord_payload


@pytest.fixture
def repo(tmp_path):
    repo = LocalRepository(data_dir=str(tmp_path))
    return repo


@pytest.fixture(autouse=True)
def set_cogent(monkeypatch):
    monkeypatch.setenv("COGENT", "alpha")


def _create_channel(repo, name):
    ch = Channel(name=name, channel_type=ChannelType.NAMED)
    repo.upsert_channel(ch)
    return repo.get_channel_by_name(name)


def test_enrich_adds_history_from_dm_channel(repo):
    """Inbound DM messages are read from the per-author fine-grained channel."""
    ch = _create_channel(repo, "io:discord:alpha:dm:user123")

    # Write some inbound messages
    for i, text in enumerate(["hello", "how are you?"]):
        repo.append_channel_message(ChannelMessage(
            channel=ch.id,
            payload={
                "author": "TestUser",
                "author_id": "user123",
                "content": text,
                "message_id": f"msg{i}",
                "channel_id": "chan456",
            },
        ))

    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "latest message",
        "message_id": "msg99",
        "channel_id": "chan456",
        "is_dm": True,
    }

    result = enrich_discord_payload(repo, payload)

    assert "_history" in result
    assert "hello" in result["_history"]
    assert "how are you?" in result["_history"]
    assert "TestUser" in result["_history"]


def test_enrich_includes_outbound_replies(repo):
    """Bot replies from the replies channel are included in history."""
    dm_ch = _create_channel(repo, "io:discord:alpha:dm:user123")
    replies_ch = _create_channel(repo, "io:discord:alpha:replies")

    # Inbound message
    repo.append_channel_message(ChannelMessage(
        channel=dm_ch.id,
        payload={
            "author": "TestUser",
            "author_id": "user123",
            "content": "hello",
            "message_id": "msg1",
            "channel_id": "chan456",
        },
    ))

    # Bot reply (matching channel)
    repo.append_channel_message(ChannelMessage(
        channel=replies_ch.id,
        payload={
            "channel": "chan456",
            "content": "Hi there!",
            "reply_to": "msg1",
        },
    ))

    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "follow up",
        "message_id": "msg2",
        "channel_id": "chan456",
        "is_dm": True,
    }

    result = enrich_discord_payload(repo, payload)
    assert "Hi there!" in result["_history"]
    assert "alpha" in result["_history"]  # bot name


def test_enrich_filters_replies_by_channel(repo):
    """Only replies to the same Discord channel are included."""
    dm_ch = _create_channel(repo, "io:discord:alpha:dm:user123")
    replies_ch = _create_channel(repo, "io:discord:alpha:replies")

    repo.append_channel_message(ChannelMessage(
        channel=dm_ch.id,
        payload={
            "author": "TestUser",
            "author_id": "user123",
            "content": "hello",
            "message_id": "msg1",
            "channel_id": "chan456",
        },
    ))

    # Reply to a different channel — should NOT appear
    repo.append_channel_message(ChannelMessage(
        channel=replies_ch.id,
        payload={
            "channel": "other_channel",
            "content": "wrong channel reply",
        },
    ))

    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "hello again",
        "message_id": "msg2",
        "channel_id": "chan456",
        "is_dm": True,
    }

    result = enrich_discord_payload(repo, payload)
    history = result.get("_history", "")
    assert "wrong channel reply" not in history


def test_enrich_guild_message(repo):
    """Guild messages use the per-channel fine-grained channel."""
    ch = _create_channel(repo, "io:discord:alpha:message:chan789")

    repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={
            "author": "Someone",
            "content": "earlier message",
            "message_id": "msg1",
            "channel_id": "chan789",
        },
    ))

    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "new message",
        "message_id": "msg2",
        "channel_id": "chan789",
        "is_dm": False,
        "channel_name": "general",
    }

    result = enrich_discord_payload(repo, payload)
    assert "_history" in result
    assert "earlier message" in result["_history"]


def test_enrich_no_history_no_key(repo):
    """When no messages exist, _history is not added."""
    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "hello",
        "message_id": "msg1",
        "channel_id": "chan456",
        "is_dm": True,
    }

    result = enrich_discord_payload(repo, payload)
    assert "_history" not in result


def test_enrich_skips_non_discord(repo):
    """Payloads without channel_id are not enriched."""
    payload = {"some": "data"}
    result = enrich_discord_payload(repo, payload)
    assert "_history" not in result


def test_enrich_skips_reactions_in_replies(repo):
    """Reaction entries in the replies channel are excluded."""
    dm_ch = _create_channel(repo, "io:discord:alpha:dm:user123")
    replies_ch = _create_channel(repo, "io:discord:alpha:replies")

    repo.append_channel_message(ChannelMessage(
        channel=dm_ch.id,
        payload={
            "author": "TestUser",
            "author_id": "user123",
            "content": "hello",
            "message_id": "msg1",
            "channel_id": "chan456",
        },
    ))

    # Reaction (should be excluded)
    repo.append_channel_message(ChannelMessage(
        channel=replies_ch.id,
        payload={
            "type": "reaction",
            "channel": "chan456",
            "message_id": "msg1",
            "emoji": "👍",
        },
    ))

    payload = {
        "author": "TestUser",
        "author_id": "user123",
        "content": "hello again",
        "message_id": "msg2",
        "channel_id": "chan456",
        "is_dm": True,
    }

    result = enrich_discord_payload(repo, payload)
    history = result.get("_history", "")
    assert "👍" not in history

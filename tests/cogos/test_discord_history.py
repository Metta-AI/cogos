"""Tests for DiscordCapability.history() method."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.io.discord.capability import DiscordCapability, DiscordError


@pytest.fixture(autouse=True)
def _set_cogent_name(monkeypatch):
    monkeypatch.setenv("COGENT", "test")


def _make_capability(scope=None):
    """Create a DiscordCapability with a mocked repo."""
    repo = MagicMock()
    process_id = uuid4()
    cap = DiscordCapability(repo=repo, process_id=process_id, run_id=uuid4())
    if scope is not None:
        cap.scope(**scope)
    return cap, repo


def _make_channel(name: str):
    """Return a mock channel object with an id."""
    ch = MagicMock()
    ch.id = uuid4()
    ch.name = name
    return ch


class TestHistoryRequest:
    """Test that history() writes the correct request payload."""

    def test_writes_request_to_api_channel(self):
        cap, repo = _make_capability()

        req_ch = _make_channel("io:discord:test:api:request")
        resp_ch = _make_channel("io:discord:test:api:response")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            if name == "io:discord:test:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel
        # No response messages -> will timeout
        repo.list_channel_messages.return_value = []

        _result = cap.history("123456", limit=25, before="msg1", after="msg2", _timeout=0.1, _poll_interval=0.05)

        # Verify request was written
        assert repo.append_channel_message.call_count == 1
        written_msg = repo.append_channel_message.call_args[0][0]
        payload = written_msg.payload
        assert payload["method"] == "history"
        assert payload["channel_id"] == "123456"
        assert payload["limit"] == 25
        assert payload["before"] == "msg1"
        assert payload["after"] == "msg2"
        assert "request_id" in payload


class TestHistoryResponse:
    """Test that history() returns messages from response."""

    def test_returns_messages_on_success(self):
        cap, repo = _make_capability()

        req_ch = _make_channel("io:discord:test:api:request")
        resp_ch = _make_channel("io:discord:test:api:response")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            if name == "io:discord:test:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel

        # We need to capture the request_id from the written message,
        # then return a matching response. Use a side_effect on list_channel_messages.
        expected_messages = [{"content": "hello", "author": "user1"}]

        def list_messages(channel_id, limit=20):
            if channel_id == resp_ch.id:
                # Get the request_id from the written request
                if repo.append_channel_message.call_count > 0:
                    req_payload = repo.append_channel_message.call_args[0][0].payload
                    resp_msg = MagicMock()
                    resp_msg.payload = {
                        "request_id": req_payload["request_id"],
                        "messages": expected_messages,
                    }
                    return [resp_msg]
            return []

        repo.list_channel_messages.side_effect = list_messages

        result = cap.history("123456", _timeout=1.0, _poll_interval=0.05)
        assert result == expected_messages

    def test_returns_error_from_response(self):
        cap, repo = _make_capability()

        req_ch = _make_channel("io:discord:test:api:request")
        resp_ch = _make_channel("io:discord:test:api:response")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            if name == "io:discord:test:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel

        def list_messages(channel_id, limit=20):
            if channel_id == resp_ch.id and repo.append_channel_message.call_count > 0:
                req_payload = repo.append_channel_message.call_args[0][0].payload
                resp_msg = MagicMock()
                resp_msg.payload = {
                    "request_id": req_payload["request_id"],
                    "error": "Unknown channel",
                }
                return [resp_msg]
            return []

        repo.list_channel_messages.side_effect = list_messages

        result = cap.history("bad_channel", _timeout=1.0, _poll_interval=0.05)
        assert isinstance(result, DiscordError)
        assert result.error == "Unknown channel"


class TestHistoryTimeout:
    """Test that history() returns DiscordError on timeout."""

    def test_timeout_returns_error(self):
        cap, repo = _make_capability()

        req_ch = _make_channel("io:discord:test:api:request")
        resp_ch = _make_channel("io:discord:test:api:response")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            if name == "io:discord:test:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel
        repo.list_channel_messages.return_value = []

        result = cap.history("123456", _timeout=0.1, _poll_interval=0.05)
        assert isinstance(result, DiscordError)
        assert "Timeout" in result.error


class TestHistoryScope:
    """Test that scope checking works for history()."""

    def test_scope_blocks_disallowed_op(self):
        cap, repo = _make_capability()
        scoped = cap.scope(ops={"send"})

        with pytest.raises(PermissionError, match="history"):
            scoped.history("123456")

    def test_scope_blocks_disallowed_channel(self):
        cap, repo = _make_capability()
        scoped = cap.scope(ops={"history"}, channels=["allowed_channel"])

        with pytest.raises(PermissionError, match="123456"):
            scoped.history("123456")

    def test_scope_allows_permitted_op_and_channel(self):
        cap, repo = _make_capability()
        scoped = cap.scope(ops={"history"}, channels=["123456"])

        req_ch = _make_channel("io:discord:test:api:request")
        resp_ch = _make_channel("io:discord:test:api:response")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            if name == "io:discord:test:api:response":
                return resp_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel
        repo.list_channel_messages.return_value = []

        # Should not raise, just timeout
        result = scoped.history("123456", _timeout=0.1, _poll_interval=0.05)
        assert isinstance(result, DiscordError)
        assert "Timeout" in result.error


class TestHistoryMissingChannels:
    """Test behavior when API channels don't exist."""

    def test_missing_request_channel(self):
        cap, repo = _make_capability()
        repo.get_channel_by_name.return_value = None

        result = cap.history("123456")
        assert isinstance(result, DiscordError)
        assert "request channel" in result.error

    def test_missing_response_channel(self):
        cap, repo = _make_capability()
        req_ch = _make_channel("io:discord:test:api:request")

        def get_channel(name):
            if name == "io:discord:test:api:request":
                return req_ch
            return None

        repo.get_channel_by_name.side_effect = get_channel

        result = cap.history("123456")
        assert isinstance(result, DiscordError)
        assert "response channel" in result.error

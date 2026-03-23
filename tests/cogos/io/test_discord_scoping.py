"""Tests for DiscordCapability scoping: _narrow(), _check(), method guards."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.discord.capability import DiscordCapability, DiscordError


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.get_channel_by_name.return_value = None
    mock.list_channel_messages.return_value = []
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestUnscopedAllowsAnyChannel:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_unscoped_send_any_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid)
        result = cap.send("chan-123", "hello")
        assert not isinstance(result, DiscordError)
        assert result.channel == "chan-123"
        mock_sqs.assert_called_once()

    @patch("cogos.io.discord.capability.time.time", return_value=1234.567)
    @patch("cogos.io.discord.capability._send_sqs")
    def test_send_includes_reply_timing_metadata(self, mock_sqs, _mock_time, repo, pid):
        run_id = uuid4()
        trace_id = uuid4()

        cap = DiscordCapability(repo, pid, run_id=run_id, trace_id=trace_id)
        result = cap.send("chan-123", "hello")

        assert not isinstance(result, DiscordError)
        assert result.channel == "chan-123"
        body = mock_sqs.call_args.args[0]
        assert body["channel"] == "chan-123"
        assert body["content"] == "hello"
        meta = body["_meta"]
        assert meta["queued_at_ms"] == 1234567
        assert meta["trace_id"] == str(trace_id)
        assert meta["process_id"] == str(pid)
        assert meta["run_id"] == str(run_id)
        assert "cogent_name" in meta

    @patch("cogos.io.discord.capability.time.time", return_value=1234.567)
    @patch("cogos.io.discord.capability._send_sqs")
    def test_send_without_trace_id_sets_none(self, mock_sqs, _mock_time, repo, pid):
        cap = DiscordCapability(repo, pid, run_id=uuid4())
        cap.send("chan-123", "hello")
        meta = mock_sqs.call_args.args[0]["_meta"]
        assert meta["trace_id"] is None


class TestScopedChannelsAllowsMatching:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_send_allowed_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123", "chan-456"])
        result = cap.send("chan-123", "hello")
        assert not isinstance(result, DiscordError)
        assert result.channel == "chan-123"

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_react_allowed_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123"])
        result = cap.react("chan-123", "msg-1", "👍")
        assert not isinstance(result, DiscordError)
        assert result.type == "reaction"

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_create_thread_allowed_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123"])
        result = cap.create_thread("chan-123", "Topic")
        assert not isinstance(result, DiscordError)
        assert result.type == "thread_create"


class TestScopedChannelsDeniesNonMatching:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_send_denied_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123"])
        with pytest.raises(PermissionError):
            cap.send("chan-999", "hello")

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_react_denied_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123"])
        with pytest.raises(PermissionError):
            cap.react("chan-999", "msg-1", "👍")

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_create_thread_denied_channel(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(channels=["chan-123"])
        with pytest.raises(PermissionError):
            cap.create_thread("chan-999", "Topic")


class TestScopedOpsDenies:
    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_ops_denies_dm(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(ops={"send", "react"})
        with pytest.raises(PermissionError):
            cap.dm("user-1", "hi")

    @patch("cogos.io.discord.capability._send_sqs")
    def test_scoped_ops_allows_send(self, mock_sqs, repo, pid):
        cap = DiscordCapability(repo, pid).scope(ops={"send"})
        result = cap.send("chan-123", "hello")
        assert not isinstance(result, DiscordError)
        assert result.channel == "chan-123"

    def test_scoped_ops_denies_receive(self, repo, pid):
        cap = DiscordCapability(repo, pid).scope(ops={"send"})
        with pytest.raises(PermissionError):
            cap.receive()


class TestNarrow:
    def test_narrow_intersects_channels(self, repo, pid):
        cap = DiscordCapability(repo, pid)
        s1 = cap.scope(channels=["chan-1", "chan-2", "chan-3"])
        s2 = s1.scope(channels=["chan-2", "chan-3", "chan-4"])
        assert set(s2._scope["channels"]) == {"chan-2", "chan-3"}

    def test_narrow_one_side_channels_keeps_it(self, repo, pid):
        cap = DiscordCapability(repo, pid)
        s1 = cap.scope(channels=["chan-1"])
        s2 = s1.scope(ops={"send"})
        assert s2._scope["channels"] == ["chan-1"]
        assert s2._scope["ops"] == {"send"}

    def test_narrow_intersects_ops(self, repo, pid):
        cap = DiscordCapability(repo, pid)
        s1 = cap.scope(ops={"send", "react", "dm"})
        s2 = s1.scope(ops={"send", "create_thread"})
        assert s2._scope["ops"] == {"send"}

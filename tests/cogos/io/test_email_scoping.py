"""Tests for EmailCapability scoping: _narrow(), _check(), send/receive guards."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.email.capability import EmailCapability


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.get_channel_by_name.return_value = None
    mock.list_channel_messages.return_value = []
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestScopedTo:
    @patch("cogos.io.email.capability._get_sender")
    def test_scoped_to_allows_matching_recipient(self, mock_get_sender, repo, pid):
        mock_sender = MagicMock()
        mock_sender.send.return_value = {"MessageId": "msg-1"}
        mock_get_sender.return_value = mock_sender

        cap = EmailCapability(repo, pid).scope(to=["a@b.com"])
        result = cap.send(to="a@b.com", subject="Hi", body="Hello")
        assert result.to == "a@b.com"

    def test_scoped_to_denies_non_matching_recipient(self, repo, pid):
        cap = EmailCapability(repo, pid).scope(to=["a@b.com"])
        with pytest.raises(PermissionError):
            cap.send(to="evil@bad.com", subject="Hi", body="Hello")


class TestScopedOps:
    def test_scoped_ops_denies_send(self, repo, pid):
        cap = EmailCapability(repo, pid).scope(ops={"receive"})
        with pytest.raises(PermissionError):
            cap.send(to="a@b.com", subject="Hi", body="Hello")

    def test_scoped_ops_denies_receive(self, repo, pid):
        cap = EmailCapability(repo, pid).scope(ops={"send"})
        with pytest.raises(PermissionError):
            cap.receive()

    @patch("cogos.io.email.capability._get_sender")
    def test_scoped_ops_allows_send(self, mock_get_sender, repo, pid):
        mock_sender = MagicMock()
        mock_sender.send.return_value = {"MessageId": "msg-1"}
        mock_get_sender.return_value = mock_sender

        cap = EmailCapability(repo, pid).scope(ops={"send"})
        result = cap.send(to="a@b.com", subject="Hi", body="Hello")
        assert result.to == "a@b.com"

    def test_scoped_ops_allows_receive(self, repo, pid):
        cap = EmailCapability(repo, pid).scope(ops={"receive"})
        cap.receive()  # should not raise


class TestNarrow:
    def test_narrow_intersects_recipients(self, repo, pid):
        cap = EmailCapability(repo, pid)
        s1 = cap.scope(to=["a@b.com", "c@d.com"])
        s2 = s1.scope(to=["a@b.com", "x@y.com"])
        assert set(s2._scope["to"]) == {"a@b.com"}

    def test_narrow_only_one_side_has_to(self, repo, pid):
        cap = EmailCapability(repo, pid)
        s1 = cap.scope(to=["a@b.com"])
        # narrowing without "to" keeps existing
        s2 = s1.scope(ops={"send"})
        assert s2._scope["to"] == ["a@b.com"]
        assert s2._scope["ops"] == {"send"}

    def test_narrow_intersects_ops(self, repo, pid):
        cap = EmailCapability(repo, pid)
        s1 = cap.scope(ops={"send", "receive"})
        s2 = s1.scope(ops={"send"})
        assert s2._scope["ops"] == {"send"}

    def test_narrow_new_introduces_to(self, repo, pid):
        """If existing has no 'to', the new 'to' is kept."""
        cap = EmailCapability(repo, pid)
        s1 = cap.scope(ops={"send"})
        s2 = s1.scope(to=["a@b.com"])
        assert s2._scope["to"] == ["a@b.com"]


class TestUnscoped:
    @patch("cogos.io.email.capability._get_sender")
    def test_unscoped_allows_send(self, mock_get_sender, repo, pid):
        mock_sender = MagicMock()
        mock_sender.send.return_value = {"MessageId": "msg-1"}
        mock_get_sender.return_value = mock_sender

        cap = EmailCapability(repo, pid)
        result = cap.send(to="anyone@any.com", subject="Hi", body="Hello")
        assert result.to == "anyone@any.com"

    def test_unscoped_allows_receive(self, repo, pid):
        cap = EmailCapability(repo, pid)
        cap.receive()  # should not raise

"""Tests for cogos email capability — sender, EmailCapability, ingest Lambda."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.email.sender import SesSender
from cogos.io.email.capability import (
    EmailCapability, EmailError, EmailMessage, SendResult, _email_from_event,
)


# ── SesSender ─────────────────────────────────────────────────


class TestSesSender:
    @patch("cogos.io.email.sender.boto3")
    def test_send_basic(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "abc123"}
        mock_boto3.client.return_value = mock_client

        sender = SesSender(from_address="ovo@softmax-cogents.com")
        result = sender.send(to="user@example.com", subject="Hello", body="Hi there")

        assert result["MessageId"] == "abc123"
        mock_client.send_email.assert_called_once()
        call_kwargs = mock_client.send_email.call_args[1]
        assert call_kwargs["Source"] == "ovo@softmax-cogents.com"
        assert call_kwargs["Destination"] == {"ToAddresses": ["user@example.com"]}
        assert call_kwargs["Message"]["Subject"]["Data"] == "Hello"
        assert call_kwargs["Message"]["Body"]["Text"]["Data"] == "Hi there"
        assert "ReplyToAddresses" not in call_kwargs

    @patch("cogos.io.email.sender.boto3")
    def test_send_with_reply_to(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "def456"}
        mock_boto3.client.return_value = mock_client

        sender = SesSender(from_address="ovo@softmax-cogents.com")
        sender.send(to="a@b.com", subject="Re: test", body="reply", reply_to="c@d.com")

        call_kwargs = mock_client.send_email.call_args[1]
        assert call_kwargs["ReplyToAddresses"] == ["c@d.com"]


# ── EmailCapability ──────────────────────────────────────────


class FakeEvent:
    def __init__(self, payload):
        self.id = uuid4()
        self.event_type = "email:received"
        self.source = "cloudflare-email-worker"
        self.payload = payload
        self.parent_event = None
        self.created_at = None


class TestEmailFromEvent:
    def test_extracts_fields(self):
        e = FakeEvent({"from": "a@b.com", "to": "ovo@x.com", "subject": "Hi", "body": "Hello", "date": "Mon", "message_id": "123"})
        result = _email_from_event(e)
        assert isinstance(result, EmailMessage)
        assert result.sender == "a@b.com"
        assert result.to == "ovo@x.com"
        assert result.subject == "Hi"

    def test_missing_fields(self):
        e = FakeEvent({})
        result = _email_from_event(e)
        assert result.sender is None
        assert result.subject is None


class TestEmailCapabilitySend:
    @patch("cogos.io.email.capability._get_sender")
    def test_send_success(self, mock_get_sender):
        mock_sender = MagicMock()
        mock_sender.send.return_value = {"MessageId": "msg-1"}
        mock_get_sender.return_value = mock_sender

        repo = MagicMock()
        email = EmailCapability(repo, uuid4())
        result = email.send(to="a@b.com", subject="Test", body="Hi")

        assert isinstance(result, SendResult)
        assert result.message_id == "msg-1"
        assert result.to == "a@b.com"

    def test_send_missing_fields(self):
        repo = MagicMock()
        email = EmailCapability(repo, uuid4())
        result = email.send(to="", subject="", body="")
        assert isinstance(result, EmailError)
        assert "required" in result.error


class FakeChannel:
    def __init__(self, id):
        self.id = id
        self.name = "io:email:inbound"


class FakeChannelMessage:
    def __init__(self, payload):
        self.id = uuid4()
        self.channel = uuid4()
        self.sender_process = uuid4()
        self.payload = payload
        self.created_at = None


class TestEmailCapabilityReceive:
    def test_receive_returns_emails(self):
        repo = MagicMock()
        fake_ch = FakeChannel(uuid4())
        repo.get_channel_by_name.return_value = fake_ch
        repo.list_channel_messages.return_value = [
            FakeChannelMessage({"from": "a@b.com", "subject": "Hi", "body": "Hello", "to": "ovo@x.com", "date": "Mon", "message_id": "1"}),
            FakeChannelMessage({"from": "c@d.com", "subject": "Hey", "body": "World", "to": "ovo@x.com", "date": "Tue", "message_id": "2"}),
        ]

        email = EmailCapability(repo, uuid4())
        result = email.receive(limit=10)
        assert len(result) == 2
        assert isinstance(result[0], EmailMessage)
        assert result[0].sender == "a@b.com"
        repo.get_channel_by_name.assert_called_once_with("io:email:inbound")
        repo.list_channel_messages.assert_called_once_with(fake_ch.id, limit=10)

    def test_receive_default_limit(self):
        repo = MagicMock()
        fake_ch = FakeChannel(uuid4())
        repo.get_channel_by_name.return_value = fake_ch
        repo.list_channel_messages.return_value = []

        email = EmailCapability(repo, uuid4())
        email.receive()
        repo.get_channel_by_name.assert_called_once_with("io:email:inbound")
        repo.list_channel_messages.assert_called_once_with(fake_ch.id, limit=10)

    def test_receive_no_channel(self):
        repo = MagicMock()
        repo.get_channel_by_name.return_value = None

        email = EmailCapability(repo, uuid4())
        result = email.receive()
        assert result == []


# ── Ingest Lambda ────────────────────────────────────────────


class TestIngestLambda:
    @pytest.fixture(autouse=True)
    def _setup(self):
        import os
        os.environ["EMAIL_INGEST_SECRET"] = "test-secret-123"

    def _make_event(self, body, token=None):
        headers = {}
        if token:
            headers["authorization"] = f"Bearer {token}"
        return {"headers": headers, "body": json.dumps(body)}

    def test_ingest_valid(self):
        with patch("polis.io.email.handler._insert_event", return_value="evt-1") as mock_insert:
            from polis.io.email.handler import handler
            resp = handler(
                self._make_event(
                    {"event_type": "email:received", "source": "cloudflare-email-worker",
                     "payload": {"from": "a@b.com", "subject": "Hi", "cogent": "ovo"}},
                    token="test-secret-123",
                ),
                None,
            )
            assert resp["statusCode"] == 200
            assert "evt-1" in resp["body"]
            mock_insert.assert_called_once_with("ovo", "email:received", "cloudflare-email-worker",
                                                 {"from": "a@b.com", "subject": "Hi", "cogent": "ovo"})

    def test_ingest_unauthorized(self):
        from polis.io.email.handler import handler
        resp = handler(
            self._make_event(
                {"event_type": "email:received", "source": "x", "payload": {"cogent": "ovo"}},
                token="wrong-token",
            ),
            None,
        )
        assert resp["statusCode"] == 401

    def test_ingest_no_token(self):
        from polis.io.email.handler import handler
        resp = handler(
            self._make_event({"event_type": "email:received", "source": "x", "payload": {"cogent": "ovo"}}),
            None,
        )
        assert resp["statusCode"] == 401

    def test_ingest_missing_cogent(self):
        from polis.io.email.handler import handler
        resp = handler(
            self._make_event(
                {"event_type": "email:received", "source": "x", "payload": {"from": "a@b.com"}},
                token="test-secret-123",
            ),
            None,
        )
        assert resp["statusCode"] == 400

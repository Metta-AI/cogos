"""Email capability — send and receive emails."""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.io.email.sender import SesSender

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class SendResult(BaseModel):
    message_id: str
    to: str
    subject: str


class EmailMessage(BaseModel):
    sender: str | None = None  # 'from' is reserved in python
    to: str | None = None
    subject: str | None = None
    body: str | None = None
    date: str | None = None
    message_id: str | None = None


class EmailError(BaseModel):
    error: str


# ── Helpers ──────────────────────────────────────────────────


def _get_sender() -> SesSender:
    cogent_name = os.environ.get("COGENT_NAME", "")
    domain = os.environ.get("EMAIL_DOMAIN", "softmax-cogents.com")
    region = os.environ.get("AWS_REGION", "us-east-1")
    from_address = f"{cogent_name}@{domain}"
    return SesSender(from_address=from_address, region=region)


def _email_from_event(e) -> EmailMessage:
    """Legacy helper for constructing EmailMessage from an event-like object."""
    p = e.payload or {}
    return EmailMessage(
        sender=p.get("from"),
        to=p.get("to"),
        subject=p.get("subject"),
        body=p.get("body"),
        date=p.get("date"),
        message_id=p.get("message_id"),
    )


def _email_from_channel_message(msg) -> EmailMessage:
    """Construct an EmailMessage from a ChannelMessage."""
    p = msg.payload or {}
    return EmailMessage(
        sender=p.get("from"),
        to=p.get("to"),
        subject=p.get("subject"),
        body=p.get("body"),
        date=p.get("date"),
        message_id=p.get("message_id"),
    )


# ── Capability ───────────────────────────────────────────────


class EmailCapability(Capability):
    """Send and receive emails.

    Usage:
        email.send(to="user@example.com", subject="Hi", body="Hello")
        emails = email.receive(limit=10)
    """

    ALL_OPS = {"send", "receive"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}

        # "to" recipients: intersection if both exist, otherwise keep whichever exists
        old_to = existing.get("to")
        new_to = requested.get("to")
        if old_to is not None and new_to is not None:
            result["to"] = list(set(old_to) & set(new_to))
        elif old_to is not None:
            result["to"] = old_to
        elif new_to is not None:
            result["to"] = new_to

        # "ops": intersection of op sets
        old_ops = existing.get("ops")
        new_ops = requested.get("ops")
        if old_ops is not None and new_ops is not None:
            result["ops"] = set(old_ops) & set(new_ops)
        elif old_ops is not None:
            result["ops"] = old_ops
        elif new_ops is not None:
            result["ops"] = new_ops

        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return

        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"EmailCapability: '{op}' not allowed (allowed: {allowed_ops})")

        if op == "send":
            to = context.get("to")
            allowed_to = self._scope.get("to")
            if to is not None and allowed_to is not None and to not in allowed_to:
                raise PermissionError(
                    f"EmailCapability: sending to '{to}' not allowed (allowed: {allowed_to})"
                )

    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> SendResult | EmailError:
        to = to.strip()
        subject = subject.strip()
        if not to or not subject:
            return EmailError(error="'to' and 'subject' are required")

        self._check("send", to=to)

        sender = _get_sender()
        response = sender.send(to=to, subject=subject, body=body, reply_to=reply_to)
        return SendResult(
            message_id=response.get("MessageId", ""),
            to=to,
            subject=subject,
        )

    def receive(self, limit: int = 10) -> list[EmailMessage]:
        self._check("receive")
        ch = self.repo.get_channel_by_name("io:email:inbound")
        if ch is None:
            return []
        messages = self.repo.list_channel_messages(ch.id, limit=limit)
        return [_email_from_channel_message(m) for m in messages]

    def __repr__(self) -> str:
        return "<EmailCapability send() receive()>"

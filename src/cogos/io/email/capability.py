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
    p = e.payload or {}
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
        emails = email.receive(limit=5)
    """

    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> SendResult | EmailError:
        to = to.strip()
        subject = subject.strip()
        if not to or not subject:
            return EmailError(error="'to' and 'subject' are required")

        sender = _get_sender()
        response = sender.send(to=to, subject=subject, body=body, reply_to=reply_to)
        return SendResult(
            message_id=response.get("MessageId", ""),
            to=to,
            subject=subject,
        )

    def receive(self, limit: int = 10) -> list[EmailMessage]:
        events = self.repo.get_events(event_type="email:received", limit=limit)
        return [_email_from_event(e) for e in events]

    def __repr__(self) -> str:
        return "<EmailCapability send() receive()>"

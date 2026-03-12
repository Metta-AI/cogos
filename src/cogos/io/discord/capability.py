"""Discord capability — send messages, reactions, threads, DMs via SQS."""

from __future__ import annotations

import json
import logging
import os
import time
from uuid import UUID, uuid4

import boto3
from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class SendResult(BaseModel):
    channel: str
    content_length: int
    type: str = "message"


class DiscordMessage(BaseModel):
    content: str | None = None
    author: str | None = None
    author_id: str | None = None
    channel_id: str | None = None
    message_id: str | None = None
    is_dm: bool = False
    is_mention: bool = False
    attachments: list[dict] | None = None
    thread_id: str | None = None
    reference_message_id: str | None = None
    event_type: str | None = None


class DiscordError(BaseModel):
    error: str


# ── SQS helpers ──────────────────────────────────────────────


def _get_queue_url() -> str:
    override = os.environ.get("DISCORD_REPLY_QUEUE_URL")
    if override:
        return override
    cogent_name = os.environ.get("COGENT_NAME", "")
    safe_name = cogent_name.replace(".", "-")
    region = os.environ.get("AWS_REGION", "us-east-1")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"https://sqs.{region}.amazonaws.com/{account_id}/cogent-{safe_name}-discord-replies"


def _send_sqs(body: dict) -> None:
    region = os.environ.get("AWS_REGION", "us-east-1")
    url = _get_queue_url()
    client = boto3.client("sqs", region_name=region)
    client.send_message(QueueUrl=url, MessageBody=json.dumps(body))


def _with_reply_meta(body: dict, *, process_id: UUID, run_id: UUID | None) -> dict:
    meta = {
        "queued_at_ms": int(time.time() * 1000),
        "trace_id": str(uuid4()),
        "process_id": str(process_id),
    }
    if run_id is not None:
        meta["run_id"] = str(run_id)
    enriched = dict(body)
    enriched["_meta"] = meta
    return enriched


# ── Capability ───────────────────────────────────────────────


class DiscordCapability(Capability):
    """Send and receive Discord messages.

    Usage:
        discord.send(channel_id, "Hello!")
        discord.react(channel_id, message_id, "👍")
        discord.create_thread(channel_id, "Topic", content="First message")
        discord.dm(user_id, "Private message")
        messages = discord.receive(limit=10)
    """

    ALL_OPS = {"send", "react", "create_thread", "dm", "receive"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}

        # Channels: intersection if both exist, otherwise keep whichever exists
        e_ch = existing.get("channels")
        r_ch = requested.get("channels")
        if e_ch is not None and r_ch is not None:
            result["channels"] = list(set(e_ch) & set(r_ch))
        elif e_ch is not None:
            result["channels"] = e_ch
        elif r_ch is not None:
            result["channels"] = r_ch

        # Ops: intersection
        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = set(e_ops) & set(r_ops)
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops

        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed by scope")
        channel = context.get("channel")
        allowed_channels = self._scope.get("channels")
        if channel and allowed_channels is not None and channel not in allowed_channels:
            raise PermissionError(
                f"Channel '{channel}' not allowed by scope"
            )

    def send(
        self,
        channel: str,
        content: str,
        *,
        thread_id: str | None = None,
        reply_to: str | None = None,
        files: list[dict] | None = None,
    ) -> SendResult | DiscordError:
        """Send a message to a Discord channel."""
        if not channel or not content:
            return DiscordError(error="'channel' and 'content' are required")
        self._check("send", channel=channel)

        body: dict = {"channel": channel, "content": content}
        if thread_id:
            body["thread_id"] = thread_id
        if reply_to:
            body["reply_to"] = reply_to
        if files:
            body["files"] = files

        try:
            _send_sqs(_with_reply_meta(body, process_id=self.process_id, run_id=self.run_id))
            return SendResult(channel=channel, content_length=len(content))
        except Exception as e:
            return DiscordError(error=str(e))

    def react(
        self,
        channel: str,
        message_id: str,
        emoji: str,
    ) -> SendResult | DiscordError:
        """Add a reaction to a message."""
        if not channel or not message_id or not emoji:
            return DiscordError(error="'channel', 'message_id', and 'emoji' are required")
        self._check("react", channel=channel)

        try:
            _send_sqs(_with_reply_meta({
                "type": "reaction",
                "channel": channel,
                "message_id": message_id,
                "emoji": emoji,
            }, process_id=self.process_id, run_id=self.run_id))
            return SendResult(channel=channel, content_length=0, type="reaction")
        except Exception as e:
            return DiscordError(error=str(e))

    def create_thread(
        self,
        channel: str,
        thread_name: str,
        content: str = "",
        *,
        message_id: str | None = None,
    ) -> SendResult | DiscordError:
        """Create a new thread in a channel."""
        if not channel or not thread_name:
            return DiscordError(error="'channel' and 'thread_name' are required")
        self._check("create_thread", channel=channel)

        body: dict = {
            "type": "thread_create",
            "channel": channel,
            "thread_name": thread_name,
        }
        if content:
            body["content"] = content
        if message_id:
            body["message_id"] = message_id

        try:
            _send_sqs(_with_reply_meta(body, process_id=self.process_id, run_id=self.run_id))
            return SendResult(channel=channel, content_length=len(content), type="thread_create")
        except Exception as e:
            return DiscordError(error=str(e))

    def dm(self, user_id: str, content: str) -> SendResult | DiscordError:
        """Send a direct message to a user."""
        if not user_id or not content:
            return DiscordError(error="'user_id' and 'content' are required")
        self._check("dm")

        try:
            _send_sqs(_with_reply_meta(
                {"type": "dm", "user_id": user_id, "content": content},
                process_id=self.process_id,
                run_id=self.run_id,
            ))
            return SendResult(channel=f"dm:{user_id}", content_length=len(content), type="dm")
        except Exception as e:
            return DiscordError(error=str(e))

    def receive(self, limit: int = 10, event_type: str | None = None) -> list[DiscordMessage]:
        """Read recent Discord messages from channels.

        Args:
            limit: Max messages to return.
            event_type: Filter by event type (discord:dm, discord:mention, discord:message).
                        If None, returns messages from all discord channels.
        """
        self._check("receive")

        if event_type:
            # Single channel: io:discord:dm, io:discord:mention, io:discord:message
            channel_names = [f"io:discord:{event_type.split(':')[1]}"]
        else:
            channel_names = ["io:discord:dm", "io:discord:mention", "io:discord:message"]

        messages: list[DiscordMessage] = []
        for name in channel_names:
            ch = self.repo.get_channel_by_name(name)
            if ch is None:
                continue
            for msg in self.repo.list_channel_messages(ch.id, limit=limit):
                messages.append(_message_from_channel_message(msg))

        # Sort by created_at and apply limit across all channels
        messages.sort(key=lambda m: m.message_id or "")
        return messages[:limit]

    def __repr__(self) -> str:
        return "<DiscordCapability send() react() create_thread() dm() receive()>"


def _message_from_event(e) -> DiscordMessage:
    """Legacy helper for constructing DiscordMessage from an event-like object."""
    p = e.payload or {}
    return DiscordMessage(
        content=p.get("content"),
        author=p.get("author"),
        author_id=p.get("author_id"),
        channel_id=p.get("channel_id"),
        message_id=p.get("message_id"),
        is_dm=p.get("is_dm", False),
        is_mention=p.get("is_mention", False),
        attachments=p.get("attachments"),
        thread_id=p.get("thread_id"),
        reference_message_id=p.get("reference_message_id"),
        event_type=p.get("event_type"),
    )


def _message_from_channel_message(msg) -> DiscordMessage:
    """Construct a DiscordMessage from a ChannelMessage."""
    p = msg.payload or {}
    return DiscordMessage(
        content=p.get("content"),
        author=p.get("author"),
        author_id=p.get("author_id"),
        channel_id=p.get("channel_id"),
        message_id=p.get("message_id"),
        is_dm=p.get("is_dm", False),
        is_mention=p.get("is_mention", False),
        attachments=p.get("attachments"),
        thread_id=p.get("thread_id"),
        reference_message_id=p.get("reference_message_id"),
        event_type=p.get("event_type"),
    )

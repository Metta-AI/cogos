"""Discord capability — send messages, reactions, threads, DMs via SQS."""

from __future__ import annotations

import json
import logging
import os
import time
from uuid import UUID, uuid4

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.db.models.discord_metadata import DiscordChannel as DiscordChannelInfo
from cogos.db.models.discord_metadata import DiscordGuild as DiscordGuildInfo

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
    is_bot: bool = False
    attachments: list[dict] | None = None
    thread_id: str | None = None
    reference_message_id: str | None = None
    message_type: str | None = None
    timestamp: str | None = None


class DiscordError(BaseModel):
    error: str


# ── SQS helpers ──────────────────────────────────────────────


_DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_DISCORD_REPLIES_QUEUE = os.environ.get("DISCORD_REPLIES_QUEUE", "cogtainer-discord-replies")


def _send_sqs(body: dict, *, runtime=None) -> None:
    """Send a message to the Discord replies SQS queue via runtime."""
    if runtime is None:
        from cogtainer.runtime.factory import create_executor_runtime
        runtime = create_executor_runtime()
    queue_name = _DISCORD_REPLIES_QUEUE
    runtime.send_queue_message(queue_name, json.dumps(body))


def _write_replies_channel(repo, cogent_name: str, body: dict) -> None:
    if repo is None:
        return
    try:
        from cogos.db.models import Channel as ChannelModel
        from cogos.db.models import ChannelMessage
        from cogos.db.models.channel import ChannelType

        candidates = []
        if cogent_name:
            candidates.append(f"io:discord:{cogent_name}:replies")
        candidates.append("io:discord:replies")

        ch = None
        for name in candidates:
            ch = repo.get_channel_by_name(name)
            if ch is not None:
                break

        if ch is None:
            create_name = candidates[0]
            ch = ChannelModel(name=create_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
            ch = repo.get_channel_by_name(create_name)
            if ch is None:
                return
        repo.append_channel_message(ChannelMessage(channel=ch.id, payload=body))
    except Exception:
        logger.debug("Failed to write to replies channel", exc_info=True)


def _with_reply_meta(
    body: dict, *, process_id: UUID, run_id: UUID | None,
    trace_id: UUID | None = None, cogent_name: str = "",
) -> dict:
    meta = {
        "queued_at_ms": int(time.time() * 1000),
        "trace_id": str(trace_id) if trace_id else str(uuid4()),
        "process_id": str(process_id),
        "cogent_name": cogent_name,
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

    ALL_OPS = {"send", "react", "create_thread", "dm", "receive", "list_channels", "list_guilds", "history"}

    def __init__(self, repo, process_id, **kwargs):
        super().__init__(repo, process_id, **kwargs)
        self._cogent_name = os.environ.get("COGENT", "")

    def handle(self) -> str:
        """The cogent's Discord persona name (mentionable as @cogent:{name})."""
        return self._cogent_name

    def profile(self) -> str:
        """Return Discord identity as markdown for prompt injection."""
        if self._cogent_name:
            return f"- **Discord Persona:** {self._cogent_name} (mentionable as @cogent:{self._cogent_name})\n"
        return ""

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
        files: list[str | dict] | None = None,
        react: str | None = None,
    ) -> SendResult | DiscordError:
        """Send a message to a Discord channel.

        files can be blob keys (str) or dicts with url/filename.
        react is an optional emoji to add as a reaction to the sent message.
        """
        if not channel or not content:
            return DiscordError(error="'channel' and 'content' are required")
        self._check("send", channel=channel)

        body: dict = {"channel": channel, "content": content}
        if thread_id:
            body["thread_id"] = thread_id
        if reply_to:
            body["reply_to"] = reply_to
        if react:
            body["react"] = react
        if files:
            file_specs = []
            for f in files:
                if isinstance(f, str):
                    file_specs.append({"s3_key": f, "filename": f.rsplit("/", 1)[-1]})
                else:
                    file_specs.append(f)
            body["files"] = file_specs

        enriched = _with_reply_meta(
            body, process_id=self.process_id, run_id=self.run_id,
            trace_id=self.trace_id, cogent_name=self._cogent_name,
        )
        _write_replies_channel(self.repo, self._cogent_name, enriched)
        try:
            _send_sqs(enriched, runtime=self._runtime)
        except Exception as e:
            logger.debug("SQS send failed (channel write still succeeded): %s", e)
        return SendResult(channel=channel, content_length=len(content))

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

        enriched = _with_reply_meta({
            "type": "reaction",
            "channel": channel,
            "message_id": message_id,
            "emoji": emoji,
        }, process_id=self.process_id, run_id=self.run_id,
            trace_id=self.trace_id, cogent_name=self._cogent_name,
        )
        _write_replies_channel(self.repo, self._cogent_name, enriched)
        try:
            _send_sqs(enriched, runtime=self._runtime)
        except Exception as e:
            logger.debug("SQS send failed (channel write still succeeded): %s", e)
        return SendResult(channel=channel, content_length=0, type="reaction")

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

        enriched = _with_reply_meta(
            body, process_id=self.process_id, run_id=self.run_id,
            trace_id=self.trace_id, cogent_name=self._cogent_name,
        )
        _write_replies_channel(self.repo, self._cogent_name, enriched)
        try:
            _send_sqs(enriched, runtime=self._runtime)
        except Exception as e:
            logger.debug("SQS send failed (channel write still succeeded): %s", e)
        return SendResult(channel=channel, content_length=len(content), type="thread_create")

    def dm(
        self, user_id: str, content: str, *,
        files: list[str | dict] | None = None, react: str | None = None,
    ) -> SendResult | DiscordError:
        """Send a direct message to a user.

        files can be blob keys (str) or dicts with url/filename.
        react is an optional emoji to add as a reaction to the sent message.
        """
        if not user_id or not content:
            return DiscordError(error="'user_id' and 'content' are required")
        self._check("dm")

        body: dict = {"type": "dm", "user_id": user_id, "content": content}
        if react:
            body["react"] = react
        if files:
            file_specs = []
            for f in files:
                if isinstance(f, str):
                    file_specs.append({"s3_key": f, "filename": f.rsplit("/", 1)[-1]})
                else:
                    file_specs.append(f)
            body["files"] = file_specs

        enriched = _with_reply_meta(
            body, process_id=self.process_id, run_id=self.run_id,
            trace_id=self.trace_id, cogent_name=self._cogent_name,
        )
        _write_replies_channel(self.repo, self._cogent_name, enriched)
        try:
            _send_sqs(enriched, runtime=self._runtime)
        except Exception as e:
            logger.debug("SQS send failed (channel write still succeeded): %s", e)
        return SendResult(channel=f"dm:{user_id}", content_length=len(content), type="dm")

    def receive(self, limit: int = 10, message_type: str | None = None) -> list[DiscordMessage]:
        """Read recent Discord messages from channels.

        Args:
            limit: Max messages to return.
            message_type: Filter by message type using "discord:<type>" format
                          (e.g. "discord:dm", "discord:mention", "discord:message").
                          If None, returns messages from all discord channels.
        """
        self._check("receive")

        if message_type:
            channel_names = [f"io:discord:{self._cogent_name}:{message_type.split(':')[1]}"]
        else:
            channel_names = [
                f"io:discord:{self._cogent_name}:dm",
                f"io:discord:{self._cogent_name}:mention",
                f"io:discord:{self._cogent_name}:message",
            ]

        messages: list[DiscordMessage] = []
        for name in channel_names:
            ch = self.repo.get_channel_by_name(name)
            if ch is None:
                continue
            for msg in self.repo.list_channel_messages(ch.id, limit=limit):
                messages.append(_message_from_channel_message(msg))

        # Sort by message_id and apply limit across all channels
        messages.sort(key=lambda m: m.message_id or "")
        return messages[:limit]

    def list_guilds(self) -> list[DiscordGuildInfo]:
        """List guilds the bot is connected to."""
        self._check("list_guilds")
        return self.repo.list_discord_guilds()

    def list_channels(self, guild_id: str | None = None) -> list[DiscordChannelInfo]:
        """List available Discord channels. Optionally filter by guild."""
        self._check("list_channels")
        channels = self.repo.list_discord_channels(guild_id=guild_id)
        allowed = self._scope.get("channels")
        if allowed is not None:
            channels = [ch for ch in channels if ch.channel_id in allowed]
        return channels

    def history(
        self,
        channel_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
        *,
        _timeout: float = 15.0,
        _poll_interval: float = 0.5,
    ) -> list[dict] | DiscordError:
        """Fetch message history for a Discord channel.

        Sends a request to the Discord API bridge and polls for the response.

        Args:
            channel_id: The Discord channel ID to fetch history from.
            limit: Maximum number of messages to return (default 50).
            before: Fetch messages before this message ID.
            after: Fetch messages after this message ID.
            _timeout: How long to wait for a response (seconds).
            _poll_interval: How often to poll for a response (seconds).

        Returns:
            A list of message dicts on success, or a DiscordError on failure/timeout.
        """
        self._check("history", channel=channel_id)

        request_id = str(uuid4())

        # Write request to the API request channel
        req_channel = self.repo.get_channel_by_name(f"io:discord:{self._cogent_name}:api:request")
        if req_channel is None:
            return DiscordError(error="Discord API request channel not found")

        from cogos.db.models import ChannelMessage

        self.repo.append_channel_message(
            ChannelMessage(
                channel=req_channel.id,
                sender_process=self.process_id,
                payload={
                    "request_id": request_id,
                    "method": "history",
                    "channel_id": channel_id,
                    "limit": limit,
                    "before": before,
                    "after": after,
                },
            )
        )

        # Poll the response channel for a matching response
        resp_channel = self.repo.get_channel_by_name(f"io:discord:{self._cogent_name}:api:response")
        if resp_channel is None:
            return DiscordError(error="Discord API response channel not found")

        deadline = time.time() + _timeout
        while time.time() < deadline:
            for msg in self.repo.list_channel_messages(resp_channel.id, limit=20):
                if msg.payload.get("request_id") == request_id:
                    if "error" in msg.payload:
                        return DiscordError(error=msg.payload["error"])
                    return msg.payload.get("messages", [])
            time.sleep(_poll_interval)

        return DiscordError(error="Timeout waiting for history response")

    def __repr__(self) -> str:
        return (
            "<DiscordCapability send() react() create_thread() dm()"
            " receive() list_channels() list_guilds() history()>"
        )


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
        message_type=p.get("message_type"),
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
        message_type=p.get("message_type"),
    )

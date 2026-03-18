"""Discord bridge: gateway relay writing inbound messages to cogos DB.

Runs as a Fargate service. Connects to the Discord gateway, writes inbound
messages as cogos events, and long-polls an SQS queue for outbound replies.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time

import aiohttp
import boto3
import discord

from cogos.io.access import get_io_token
from cogos.io.discord.chunking import chunk_message
from cogos.io.discord.markdown import convert_markdown

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message payload builder
# ---------------------------------------------------------------------------


def _make_message_payload(
    message: discord.Message,
    message_type: str,
    *,
    is_dm: bool,
    is_mention: bool,
) -> dict:
    """Build the cogos message payload from a Discord message."""
    attachments = []
    for a in message.attachments:
        attachments.append(
            {
                "url": a.url,
                "filename": a.filename,
                "content_type": a.content_type,
                "size": a.size,
                "is_image": a.content_type.startswith("image/") if a.content_type else False,
                "width": a.width,
                "height": a.height,
            }
        )

    thread_id = None
    parent_channel_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
        parent_channel_id = str(message.channel.parent_id)

    embeds = []
    for e in message.embeds:
        embed_data: dict = {"type": e.type}
        if e.title:
            embed_data["title"] = e.title
        if e.description:
            embed_data["description"] = e.description
        if e.url:
            embed_data["url"] = e.url
        if e.image:
            embed_data["image_url"] = e.image.url
        embeds.append(embed_data)

    return {
        "content": message.content,
        "author": str(message.author),
        "author_id": str(message.author.id),
        "channel_id": str(message.channel.id),
        "guild_id": str(message.guild.id) if message.guild else None,
        "message_id": str(message.id),
        "message_type": message_type,
        "timestamp": message.created_at.isoformat(),
        "is_dm": is_dm,
        "is_mention": is_mention,
        "attachments": attachments,
        "thread_id": thread_id,
        "parent_channel_id": parent_channel_id,
        "embeds": embeds,
        "reference_message_id": (
            str(message.reference.message_id) if message.reference else None
        ),
    }


def _reply_queue_latency_ms(body: dict) -> int | None:
    meta = body.get("_meta")
    if not isinstance(meta, dict):
        return None
    queued_at_ms = meta.get("queued_at_ms")
    if isinstance(queued_at_ms, str):
        if not queued_at_ms.isdigit():
            return None
        queued_at_ms = int(queued_at_ms)
    if not isinstance(queued_at_ms, int):
        return None
    return max(0, int(time.time() * 1000) - queued_at_ms)


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------


class DiscordBridge:
    """Relays Discord messages to cogos DB and SQS replies back to Discord."""

    def __init__(self):
        self.cogent_name = os.environ["COGENT_NAME"]
        self.bot_token = self._get_bot_token()
        self.reply_queue_url = os.environ.get(
            "DISCORD_REPLY_QUEUE_URL",
            os.environ.get("REPLY_QUEUE_URL", ""),
        )
        self.region = os.environ.get("AWS_REGION", "us-east-1")

        self._sqs_client = boto3.client("sqs", region_name=self.region)
        self._repo = None  # lazy init
        self._blob_bucket = os.environ.get("SESSIONS_BUCKET", "")
        self._s3_client = boto3.client("s3", region_name=self.region) if self._blob_bucket else None

        # Typing indicator tasks keyed by channel_id
        self._typing_tasks: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guilds = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _get_repo(self):
        if self._repo is None:
            from cogos.db.factory import create_repository

            self._repo = create_repository()
        return self._repo

    def _get_bot_token(self) -> str:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return token
        token = get_io_token("discord")
        if not token:
            raise RuntimeError(
                f"No Discord token found for {self.cogent_name}. "
                "Set DISCORD_BOT_TOKEN or provision via channels CLI."
            )
        return token

    MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25MB

    async def _upload_attachment_to_s3(self, attachment) -> dict | None:
        """Download a Discord attachment and upload to S3. Returns s3_key/s3_url dict or None."""
        if not self._s3_client or not self._blob_bucket:
            return None
        if attachment.size and attachment.size > self.MAX_ATTACHMENT_SIZE:
            logger.warning("Skipping oversized attachment %s (%d bytes)", attachment.filename, attachment.size)
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status != 200:
                        logger.warning("Failed to download attachment %s: HTTP %s", attachment.filename, resp.status)
                        return None
                    data = await resp.read()
        except Exception:
            logger.exception("Failed to download attachment %s", attachment.filename)
            return None

        from uuid import uuid4
        s3_key = f"blobs/{uuid4()}/{attachment.filename}"

        try:
            put_kwargs: dict = {"Bucket": self._blob_bucket, "Key": s3_key, "Body": data}
            if attachment.content_type:
                put_kwargs["ContentType"] = attachment.content_type
            self._s3_client.put_object(**put_kwargs)

            s3_url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._blob_bucket, "Key": s3_key},
                ExpiresIn=7 * 24 * 3600,
            )
            return {"s3_key": s3_key, "s3_url": s3_url}
        except Exception:
            logger.exception("Failed to upload attachment %s to S3", attachment.filename)
            return None

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    async def _sync_guild(self, guild) -> None:
        """Sync a guild and its channels to the DB."""
        from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild

        channels = [
            DiscordChannel(
                channel_id=str(ch.id),
                guild_id=str(guild.id),
                name=ch.name,
                topic=getattr(ch, "topic", None),
                category=ch.category.name if ch.category else None,
                channel_type=ch.type.name,
                position=ch.position,
            )
            for ch in guild.channels
        ]
        guild_model = DiscordGuild(
            guild_id=str(guild.id),
            cogent_name=self.cogent_name,
            name=guild.name,
            icon_url=guild.icon.url if guild.icon else None,
            member_count=guild.member_count,
        )

        def _do_sync():
            repo = self._get_repo()
            repo.upsert_discord_guild(guild_model)
            for ch in channels:
                repo.upsert_discord_channel(ch)

        await asyncio.get_event_loop().run_in_executor(None, _do_sync)
        logger.info("Synced guild %s: %d channels", guild.name, len(channels))

    async def _on_channel_delete(self, channel) -> None:
        channel_id = str(channel.id)
        def _do_delete():
            repo = self._get_repo()
            repo.delete_discord_channel(channel_id)
        await asyncio.get_event_loop().run_in_executor(None, _do_delete)

    def _setup_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bridge connected as %s", self.client.user)
            for guild in self.client.guilds:
                await self._sync_guild(guild)
            self.client.loop.create_task(self._poll_replies())
            self.client.loop.create_task(self._poll_api_requests())

        @self.client.event
        async def on_guild_channel_create(channel):
            await self._sync_guild(channel.guild)

        @self.client.event
        async def on_guild_channel_update(before, after):
            await self._sync_guild(after.guild)

        @self.client.event
        async def on_guild_channel_delete(channel):
            await self._on_channel_delete(channel)

        @self.client.event
        async def on_guild_join(guild):
            await self._sync_guild(guild)

        @self.client.event
        async def on_guild_remove(guild):
            repo = self._get_repo()
            repo.delete_discord_guild(str(guild.id))

        @self.client.event
        async def on_message(message: discord.Message):
            logger.info("on_message from %s (bot=%s) in %s: %s", message.author, message.author.bot, message.channel, message.content[:80] if message.content else "(empty)")
            # Ignore our own messages and any other bot messages
            if message.author == self.client.user:
                return
            if message.author.bot:
                return
            await self._relay_to_db(message)

    def _get_or_create_channel(self, repo, channel_name: str):
        """Look up a channel by name, creating it if missing."""
        from cogos.db.models import Channel, ChannelType
        ch = repo.get_channel_by_name(channel_name)
        if ch is None:
            logger.info("Creating channel %s", channel_name)
            ch = Channel(name=channel_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
            ch = repo.get_channel_by_name(channel_name)
        return ch

    async def _relay_to_db(self, message: discord.Message):
        """Classify a Discord message and write it as a channel message."""
        if isinstance(message.channel, discord.DMChannel):
            message_type = "discord:dm"
        elif self.client.user and self.client.user.mentioned_in(message):
            message_type = "discord:mention"
        else:
            message_type = "discord:message"

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        payload = _make_message_payload(message, message_type, is_dm=is_dm, is_mention=is_mention)

        # Upload attachments to S3
        if self._s3_client and payload.get("attachments"):
            for att_payload, att_obj in zip(payload["attachments"], message.attachments):
                s3_result = await self._upload_attachment_to_s3(att_obj)
                if s3_result:
                    att_payload["s3_key"] = s3_result["s3_key"]
                    att_payload["s3_url"] = s3_result["s3_url"]

        # Generate trace for DMs and mentions (messages that trigger processing)
        trace_id = None
        trace_meta = None
        if message_type in ("discord:dm", "discord:mention"):
            from uuid import uuid4
            bridge_received_at_ms = int(time.time() * 1000)
            trace_id = uuid4()
            trace_meta = {
                "discord_created_at_ms": int(message.created_at.timestamp() * 1000),
                "bridge_received_at_ms": bridge_received_at_ms,
            }

        try:
            from cogos.db.models import ChannelMessage
            repo = self._get_repo()

            # Get or create the catch-all channel for this message type
            channel_name = f"io:discord:{message_type.split(':')[1]}"  # io:discord:dm, io:discord:mention, io:discord:message
            ch = self._get_or_create_channel(repo, channel_name)
            if ch is None:
                raise RuntimeError(f"Failed to create Discord channel {channel_name}")

            repo.append_channel_message(ChannelMessage(
                channel=ch.id,
                sender_process=None,
                payload=payload,
                idempotency_key=f"discord:{message.id}",
                trace_id=trace_id,
                trace_meta=trace_meta,
            ))

            # Stamp db_written_at after successful insert
            if trace_meta is not None:
                trace_meta["db_written_at_ms"] = int(time.time() * 1000)

            logger.info("Wrote %s from %s to channel %s", message_type, message.author, channel_name)

            # Write to fine-grained per-source channel for message and dm types
            fine_channel_name = None
            if message_type == "discord:message":
                fine_channel_name = f"io:discord:message:{payload['channel_id']}"
            elif message_type == "discord:dm":
                fine_channel_name = f"io:discord:dm:{payload['author_id']}"

            if fine_channel_name:
                fine_ch = self._get_or_create_channel(repo, fine_channel_name)
                if fine_ch:
                    repo.append_channel_message(ChannelMessage(
                        channel=fine_ch.id,
                        sender_process=None,
                        payload=payload,
                    ))

            # Start typing indicator for DMs and mentions
            if message_type in ("discord:dm", "discord:mention"):
                self._start_typing(message.channel)
        except Exception:
            logger.exception("Failed to write message %s to DB", message.id)

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    def _start_typing(self, channel: discord.abc.Messageable):
        channel_id = channel.id
        old = self._typing_tasks.pop(channel_id, None)
        if old and not old.done():
            old.cancel()

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(300)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Typing indicator error for channel %s", channel_id, exc_info=True)

        self._typing_tasks[channel_id] = asyncio.create_task(_keep_typing())

    def _stop_typing(self, channel_id: int):
        task = self._typing_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # SQS reply poller
    # ------------------------------------------------------------------

    async def _poll_replies(self):
        if not self.reply_queue_url:
            logger.warning("No REPLY_QUEUE_URL set, reply polling disabled")
            return

        logger.info("Starting SQS reply poller on %s", self.reply_queue_url)
        loop = asyncio.get_event_loop()

        while True:
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self._sqs_client.receive_message(
                        QueueUrl=self.reply_queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,
                    ),
                )
                for msg in response.get("Messages", []):
                    try:
                        await self._send_reply(msg)
                    except discord.errors.NotFound:
                        logger.error("Channel not found for reply %s, discarding", msg.get("MessageId"))
                    except Exception:
                        logger.exception("Failed to send reply: %s", msg.get("MessageId"))
                        continue
                    try:
                        self._sqs_client.delete_message(
                            QueueUrl=self.reply_queue_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                    except Exception:
                        logger.exception("Failed to delete SQS message %s", msg.get("MessageId"))
            except Exception:
                logger.exception("Reply poll error")
                await asyncio.sleep(5)

    async def _send_reply(self, sqs_message: dict):
        body = json.loads(sqs_message["Body"])
        # Stamp SQS receive time for trace
        meta = body.get("_meta")
        if isinstance(meta, dict):
            meta["sqs_received_at_ms"] = int(time.time() * 1000)
        msg_type = body.get("type", "message")

        if msg_type == "dm":
            await self._handle_dm(body)
            return

        channel_id = int(body["channel"])
        self._stop_typing(channel_id)

        channel = self.client.get_channel(channel_id)
        if channel is None:
            channel = await self.client.fetch_channel(channel_id)
        if channel is None:
            logger.error("Could not find Discord channel %s", channel_id)
            return

        if msg_type == "reaction":
            await self._handle_reaction(body, channel)
        elif msg_type == "thread_create":
            await self._handle_thread_create(body, channel)
        else:
            await self._handle_message(body, channel)

    def _log_reply_send_latency(self, body: dict, *, msg_type: str, target_id: int | str):
        latency_ms = _reply_queue_latency_ms(body)
        if latency_ms is None:
            return
        meta = body.get("_meta") if isinstance(body.get("_meta"), dict) else {}
        logger.info(
            "CogOS latency discord_queue->send=%sms type=%s target=%s process=%s run=%s trace=%s",
            latency_ms,
            msg_type,
            target_id,
            meta.get("process_id", ""),
            meta.get("run_id", ""),
            meta.get("trace_id", ""),
        )

    def _log_trace_summary(self, body: dict, *, msg_type: str, target_id: int | str):
        """Log a complete trace summary if _meta contains trace_id."""
        meta = body.get("_meta")
        if not isinstance(meta, dict):
            return
        trace_id = meta.get("trace_id")
        if not trace_id:
            return

        now_ms = int(time.time() * 1000)
        queued_at_ms = meta.get("queued_at_ms")
        sqs_received_at_ms = meta.get("sqs_received_at_ms", now_ms)

        sqs_to_receive_ms = (sqs_received_at_ms - queued_at_ms) if queued_at_ms else None
        receive_to_send_ms = now_ms - sqs_received_at_ms

        logger.info(
            "CogOS trace_complete trace_id=%s type=%s target=%s "
            "process=%s run=%s "
            "sqs_to_receive_ms=%s receive_to_send_ms=%s",
            trace_id,
            msg_type,
            target_id,
            meta.get("process_id", ""),
            meta.get("run_id", ""),
            sqs_to_receive_ms,
            receive_to_send_ms,
        )

    async def _maybe_react(self, message, body: dict) -> None:
        """Add a reaction to a sent message if the payload contains a 'react' emoji."""
        react = body.get("react")
        if not react or message is None:
            return
        try:
            await message.add_reaction(react)
        except Exception:
            logger.warning("Failed to add reaction %s to message %s", react, message.id, exc_info=True)

    async def _handle_message(self, body: dict, channel):
        content = body.get("content", "")
        if content:
            content = convert_markdown(content)
        file_specs = body.get("files") or []
        thread_id = body.get("thread_id")
        reply_to = body.get("reply_to")

        target = channel
        if thread_id:
            thread = self.client.get_channel(int(thread_id))
            if thread is None:
                try:
                    thread = await self.client.fetch_channel(int(thread_id))
                except Exception:
                    logger.warning("Could not find thread %s, falling back to channel", thread_id)
            if thread:
                target = thread

        reference = None
        if reply_to:
            try:
                reference = discord.MessageReference(message_id=int(reply_to), channel_id=target.id)
            except (ValueError, TypeError):
                logger.warning("Invalid reply_to %r, sending without reference", reply_to)

        discord_files = await self._download_files(file_specs)

        sent_message = None
        if discord_files:
            first_chunk = content[:2000] if content else None
            sent_message = await target.send(content=first_chunk, files=discord_files, reference=reference)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await target.send(c)
        elif content:
            chunks = chunk_message(content)
            sent_message = await target.send(chunks[0], reference=reference)
            for c in chunks[1:]:
                await target.send(c)
        await self._maybe_react(sent_message, body)
        self._log_reply_send_latency(body, msg_type="message", target_id=target.id)
        self._log_trace_summary(body, msg_type="message", target_id=target.id)

    async def _handle_reaction(self, body: dict, channel):
        message_id = body.get("message_id")
        emoji = body.get("emoji")
        if not message_id or not emoji:
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
            self._log_reply_send_latency(body, msg_type="reaction", target_id=channel.id)
        except Exception:
            logger.exception("Failed to add reaction %s to message %s", emoji, message_id)

    async def _handle_thread_create(self, body: dict, channel):
        thread_name = body.get("thread_name", "Thread")
        message_id = body.get("message_id")
        content = body.get("content", "")

        try:
            if message_id:
                message = await channel.fetch_message(int(message_id))
                thread = await message.create_thread(name=thread_name)
            else:
                thread = await channel.create_thread(
                    name=thread_name, type=discord.ChannelType.public_thread
                )
            if content:
                for c in chunk_message(content):
                    await thread.send(c)
            self._log_reply_send_latency(body, msg_type="thread_create", target_id=channel.id)
        except Exception:
            logger.exception("Failed to create thread '%s' in channel %s", thread_name, channel.id)

    async def _handle_dm(self, body: dict):
        user_id = body.get("user_id")
        content = body.get("content", "")
        if not user_id or not content:
            return
        try:
            user = await self.client.fetch_user(int(user_id))
            dm_channel = await user.create_dm()
            self._stop_typing(dm_channel.id)
            file_specs = body.get("files") or []
            discord_files = await self._download_files(file_specs)
            sent_message = None
            if discord_files:
                first_chunk = content[:2000] if content else None
                sent_message = await dm_channel.send(content=first_chunk, files=discord_files)
                remaining = content[2000:] if content and len(content) > 2000 else ""
                for c in chunk_message(remaining):
                    await dm_channel.send(c)
            else:
                chunks = chunk_message(content)
                sent_message = await dm_channel.send(chunks[0])
                for c in chunks[1:]:
                    await dm_channel.send(c)
            await self._maybe_react(sent_message, body)
            self._log_reply_send_latency(body, msg_type="dm", target_id=dm_channel.id)
            self._log_trace_summary(body, msg_type="dm", target_id=dm_channel.id)
        except Exception:
            logger.exception("Failed to send DM to user %s", user_id)

    async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
        if not file_specs:
            return []
        files = []
        # Collect URL-based specs to download with a single session
        url_specs = []
        for spec in file_specs:
            s3_key = spec.get("s3_key")
            if s3_key and self._s3_client and self._blob_bucket:
                try:
                    resp = self._s3_client.get_object(Bucket=self._blob_bucket, Key=s3_key)
                    data = resp["Body"].read()
                    filename = spec.get("filename") or s3_key.rsplit("/", 1)[-1]
                    files.append(discord.File(io.BytesIO(data), filename=filename))
                except Exception:
                    logger.exception("Failed to download blob: %s", s3_key)
                continue
            url = spec.get("url")
            if url:
                url_specs.append(spec)

        if url_specs:
            async with aiohttp.ClientSession() as session:
                for spec in url_specs:
                    url = spec["url"]
                    filename = spec.get("filename", "file")
                    try:
                        async with session.get(url) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.read()
                            files.append(discord.File(io.BytesIO(data), filename=filename))
                    except Exception:
                        logger.exception("Failed to download file: %s", url)
        return files

    # ------------------------------------------------------------------
    # API request poller
    # ------------------------------------------------------------------

    async def _poll_api_requests(self):
        """Poll io:discord:api:request for API requests and dispatch them."""
        logger.info("Starting API request poller")
        seen_requests: set[str] = set()

        while True:
            try:
                repo = self._get_repo()
                ch = self._get_or_create_channel(repo, "io:discord:api:request")
                if ch is None:
                    await asyncio.sleep(2)
                    continue

                messages = repo.list_channel_messages(ch.id, limit=50)
                for msg in messages:
                    msg_id = str(msg.id)
                    if msg_id in seen_requests:
                        continue
                    seen_requests.add(msg_id)

                    payload = msg.payload or {}
                    request_id = payload.get("request_id", msg_id)
                    method = payload.get("method")

                    if method == "history":
                        try:
                            await self._handle_history_request(repo, payload)
                        except Exception:
                            logger.exception(
                                "Failed to handle history request %s", request_id
                            )
                            self._write_api_response(
                                repo, request_id, "error", error="internal error"
                            )
                    else:
                        logger.warning(
                            "Unknown API request method: %s (request_id=%s)",
                            method,
                            request_id,
                        )
                        self._write_api_response(
                            repo,
                            request_id,
                            "error",
                            error=f"unknown method: {method}",
                        )

                # Keep seen_requests bounded
                if len(seen_requests) > 1000:
                    # Keep the most recent 500
                    to_drop = len(seen_requests) - 500
                    it = iter(seen_requests)
                    for _ in range(to_drop):
                        seen_requests.discard(next(it))

            except Exception:
                logger.exception("API request poll error")

            await asyncio.sleep(2)

    async def _handle_history_request(self, repo, request: dict):
        """Handle a 'history' API request by fetching messages from Discord."""
        request_id = request.get("request_id", "")
        channel_id = request.get("channel_id")
        limit = request.get("limit", 50)
        before = request.get("before")
        after = request.get("after")

        if not channel_id:
            self._write_api_response(
                repo, request_id, "error", error="missing channel_id"
            )
            return

        # Fetch the Discord channel
        channel = self.client.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.client.fetch_channel(int(channel_id))
            except Exception:
                self._write_api_response(
                    repo, request_id, "error", error=f"channel {channel_id} not found"
                )
                return

        # Build history kwargs
        kwargs: dict = {"limit": min(int(limit), 100)}
        if before:
            kwargs["before"] = discord.Object(id=int(before))
        if after:
            kwargs["after"] = discord.Object(id=int(after))

        history_messages = []
        async for msg in channel.history(**kwargs):
            payload = _make_message_payload(
                msg,
                "discord:history",
                is_dm=isinstance(msg.channel, discord.DMChannel),
                is_mention=False,
            )
            history_messages.append(payload)

        # Reverse to oldest-first
        history_messages.reverse()

        self._write_api_response(
            repo, request_id, "ok", messages=history_messages
        )

    def _write_api_response(
        self,
        repo,
        request_id: str,
        status: str,
        *,
        messages: list | None = None,
        error: str | None = None,
    ):
        """Write an API response to io:discord:api:response channel."""
        from cogos.db.models import ChannelMessage

        ch = self._get_or_create_channel(repo, "io:discord:api:response")
        if ch is None:
            logger.error("Failed to create io:discord:api:response channel")
            return

        payload: dict = {
            "request_id": request_id,
            "status": status,
        }
        if messages is not None:
            payload["messages"] = messages
        if error is not None:
            payload["error"] = error

        repo.append_channel_message(
            ChannelMessage(
                channel=ch.id,
                sender_process=None,
                payload=payload,
            )
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        """Start the Discord gateway connection (blocking)."""
        self.client.run(self.bot_token, log_handler=None)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bridge = DiscordBridge()
    bridge.run()


if __name__ == "__main__":
    main()

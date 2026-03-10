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

import aiohttp
import boto3
import discord

from channels.access import get_channel_token
from cogos.io.discord.chunking import chunk_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event detail builder
# ---------------------------------------------------------------------------


def _make_event_payload(
    message: discord.Message,
    event_type: str,
    *,
    is_dm: bool,
    is_mention: bool,
) -> dict:
    """Build the cogos event payload from a Discord message."""
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
        "event_type": event_type,
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

        # Typing indicator tasks keyed by channel_id
        self._typing_tasks: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _get_repo(self):
        if self._repo is None:
            from cogos.db.repository import Repository
            self._repo = Repository.create()
        return self._repo

    def _get_bot_token(self) -> str:
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return token
        token = get_channel_token("discord")
        if not token:
            raise RuntimeError(
                f"No Discord token found for {self.cogent_name}. "
                "Set DISCORD_BOT_TOKEN or provision via channels CLI."
            )
        return token

    # ------------------------------------------------------------------
    # Discord event handlers
    # ------------------------------------------------------------------

    def _setup_handlers(self):
        @self.client.event
        async def on_ready():
            logger.info("Discord bridge connected as %s", self.client.user)
            self.client.loop.create_task(self._poll_replies())

        @self.client.event
        async def on_message(message: discord.Message):
            logger.info("on_message from %s in %s: %s", message.author, message.channel, message.content[:80] if message.content else "(empty)")
            if message.author == self.client.user:
                return
            await self._relay_to_db(message)

    async def _relay_to_db(self, message: discord.Message):
        """Classify a Discord message and write it as a cogos event."""
        if isinstance(message.channel, discord.DMChannel):
            event_type = "discord:dm"
        elif self.client.user and self.client.user.mentioned_in(message):
            event_type = "discord:mention"
        else:
            event_type = "discord:message"

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        payload = _make_event_payload(message, event_type, is_dm=is_dm, is_mention=is_mention)

        try:
            from cogos.db.models import Event
            repo = self._get_repo()
            repo.append_event(Event(
                event_type=event_type,
                source="discord",
                payload=payload,
            ))
            logger.info("Wrote %s from %s to DB", event_type, message.author)

            # Start typing indicator for DMs and mentions
            if event_type in ("discord:dm", "discord:mention"):
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

    async def _handle_message(self, body: dict, channel):
        content = body.get("content", "")
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
            reference = discord.MessageReference(message_id=int(reply_to), channel_id=target.id)

        discord_files = await self._download_files(file_specs)

        if discord_files:
            first_chunk = content[:2000] if content else None
            await target.send(content=first_chunk, files=discord_files, reference=reference)
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await target.send(c)
        elif content:
            chunks = chunk_message(content)
            await target.send(chunks[0], reference=reference)
            for c in chunks[1:]:
                await target.send(c)

    async def _handle_reaction(self, body: dict, channel):
        message_id = body.get("message_id")
        emoji = body.get("emoji")
        if not message_id or not emoji:
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
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
            for c in chunk_message(content):
                await dm_channel.send(c)
        except Exception:
            logger.exception("Failed to send DM to user %s", user_id)

    async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
        if not file_specs:
            return []
        files = []
        async with aiohttp.ClientSession() as session:
            for spec in file_specs:
                url = spec.get("url")
                filename = spec.get("filename", "file")
                if not url:
                    continue
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

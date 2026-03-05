"""Discord bridge: gateway relay between Discord and EventBridge/SQS.

Runs as a standalone Fargate service (not a Lambda). Connects to the Discord
gateway, relays inbound messages to EventBridge, and long-polls an SQS queue
for outbound replies to send back to Discord channels.

Supports:
  - Inbound: text, attachments (images/files), threads, embeds, references
  - Outbound: text, file uploads, thread replies, reactions, DMs, thread creation
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
from channels.discord.chunking import chunk_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event detail builder
# ---------------------------------------------------------------------------


def _make_event_detail(
    message: discord.Message,
    event_type: str,
    *,
    is_dm: bool,
    is_mention: bool,
) -> dict:
    """Build the EventBridge detail dict from a Discord message.

    Includes rich metadata: attachments, thread context, embeds, references.
    """
    # Attachment metadata
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

    # Thread context
    thread_id = None
    parent_channel_id = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
        parent_channel_id = str(message.channel.parent_id)

    # Embeds (link previews, rich embeds)
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
        "event_id": str(message.id),
        "payload": {
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
        },
        "source": "discord",
        "context_key": f"discord:{message.channel.id}:{message.author.id}",
        "created_at": message.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------


class DiscordBridge:
    """Relays Discord messages to EventBridge and SQS replies back to Discord."""

    def __init__(self):
        self.cogent_name = os.environ["COGENT_NAME"]
        self.bot_token = self._get_bot_token()
        self.event_bus_name = os.environ.get(
            "EVENT_BUS_NAME",
            f"cogent-{self.cogent_name.replace('.', '-')}-bus",
        )
        self.reply_queue_url = os.environ.get(
            "DISCORD_REPLY_QUEUE_URL",
            os.environ.get("REPLY_QUEUE_URL", ""),
        )
        self.region = os.environ.get("AWS_REGION", "us-east-1")

        self._eb_client = boto3.client("events", region_name=self.region)
        self._sqs_client = boto3.client("sqs", region_name=self.region)

        # Typing indicator tasks keyed by channel_id
        self._typing_tasks: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        self.client = discord.Client(intents=intents)
        self._setup_handlers()

    def _get_bot_token(self) -> str:
        """Get Discord bot token from env var or identity key-store."""
        token = os.environ.get("DISCORD_BOT_TOKEN")
        if token:
            return token
        token = get_channel_token(self.cogent_name, "discord")
        if not token:
            raise RuntimeError(
                f"No Discord token found for {self.cogent_name}. "
                "Set DISCORD_BOT_TOKEN or provision via: cogent <name> channel discord create"
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
            if message.author == self.client.user:
                return
            await self._relay_to_eventbridge(message)

    async def _relay_to_eventbridge(self, message: discord.Message):
        """Classify a Discord message and publish it to EventBridge."""
        if isinstance(message.channel, discord.DMChannel):
            event_type = "discord:dm"
        elif self.client.user and self.client.user.mentioned_in(message):
            event_type = "discord:mention"
        else:
            event_type = "discord:channel.message"

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = bool(self.client.user and self.client.user.mentioned_in(message))

        detail = _make_event_detail(message, event_type, is_dm=is_dm, is_mention=is_mention)

        try:
            response = self._eb_client.put_events(
                Entries=[
                    {
                        "Source": f"cogent.{self.cogent_name}",
                        "DetailType": event_type,
                        "Detail": json.dumps(detail),
                        "EventBusName": self.event_bus_name,
                    }
                ]
            )
            failed = response.get("FailedEntryCount", 0)
            if failed:
                entries = response.get("Entries", [])
                err = entries[0].get("ErrorMessage", "unknown") if entries else "unknown"
                logger.error("EventBridge put failed for message %s: %s", message.id, err)
            else:
                logger.debug("Relayed %s from %s", event_type, message.author)
                # Start typing indicator for DMs and mentions
                if event_type in ("discord:dm", "discord:mention"):
                    self._start_typing(message.channel)
        except Exception:
            logger.exception("Failed to relay message %s to EventBridge", message.id)

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    def _start_typing(self, channel: discord.abc.Messageable):
        """Start a typing indicator on the given channel."""
        channel_id = channel.id
        # Cancel any existing typing task for this channel
        old = self._typing_tasks.pop(channel_id, None)
        if old and not old.done():
            old.cancel()

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(300)  # max 5 min, cancelled when reply arrives
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Typing indicator error for channel %s", channel_id, exc_info=True)

        self._typing_tasks[channel_id] = asyncio.create_task(_keep_typing())

    def _stop_typing(self, channel_id: int):
        """Cancel the typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()

    # ------------------------------------------------------------------
    # SQS reply poller
    # ------------------------------------------------------------------

    async def _poll_replies(self):
        """Long-poll SQS for reply messages and send them to Discord."""
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
                    # Only delete after successful send
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
        """Parse an SQS reply message and dispatch to Discord."""
        body = json.loads(sqs_message["Body"])
        msg_type = body.get("type", "message")

        # DM by user_id -- create DM channel and send
        if msg_type == "dm":
            await self._handle_dm(body)
            return

        channel_id = int(body["channel"])

        # Stop typing before sending
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
        """Send a text message with optional files, thread targeting, and reply-to."""
        content = body.get("content", "")
        file_specs = body.get("files") or []
        thread_id = body.get("thread_id")
        reply_to = body.get("reply_to")

        # Resolve thread: send into a thread instead of the channel root
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

        # Build reply reference
        reference = None
        if reply_to:
            reference = discord.MessageReference(message_id=int(reply_to), channel_id=target.id)

        # Download and attach files
        discord_files = await self._download_files(file_specs)

        if discord_files:
            # Send files with the first chunk of content
            first_chunk = content[:2000] if content else None
            await target.send(
                content=first_chunk,
                files=discord_files,
                reference=reference,
            )
            # Send remaining text chunks without files
            remaining = content[2000:] if content and len(content) > 2000 else ""
            for c in chunk_message(remaining):
                await target.send(c)
        elif content:
            chunks = chunk_message(content)
            # First chunk gets the reply reference
            await target.send(chunks[0], reference=reference)
            for c in chunks[1:]:
                await target.send(c)

        logger.debug(
            "Sent reply to channel %s (%d chars, %d files)",
            channel.id,
            len(content),
            len(discord_files),
        )

    async def _handle_reaction(self, body: dict, channel):
        """Add an emoji reaction to a message."""
        message_id = body.get("message_id")
        emoji = body.get("emoji")
        if not message_id or not emoji:
            logger.warning("Reaction missing message_id or emoji: %s", body)
            return
        try:
            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
        except Exception:
            logger.exception("Failed to add reaction %s to message %s", emoji, message_id)

    async def _handle_thread_create(self, body: dict, channel):
        """Create a new thread on a message or channel."""
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
        """Send a direct message to a Discord user by user_id."""
        user_id = body.get("user_id")
        content = body.get("content", "")
        if not user_id:
            logger.warning("DM message missing user_id: %s", body)
            return
        if not content:
            logger.warning("DM message has no content for user %s", user_id)
            return

        try:
            user = await self.client.fetch_user(int(user_id))
            dm_channel = await user.create_dm()
            for c in chunk_message(content):
                await dm_channel.send(c)
            logger.debug("Sent DM to user %s (%d chars)", user_id, len(content))
        except Exception:
            logger.exception("Failed to send DM to user %s", user_id)

    async def _download_files(self, file_specs: list[dict]) -> list[discord.File]:
        """Download files from URLs and wrap as discord.File objects."""
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
                            logger.warning("Failed to download %s: HTTP %d", url, resp.status)
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

"""Discord channel: live Gateway connection for DMs, mentions, and channel messages."""

from __future__ import annotations

import asyncio
import logging

import discord

from channels.base import Channel, ChannelMode, InboundEvent

logger = logging.getLogger(__name__)


class DiscordChannel(Channel):
    mode = ChannelMode.LIVE

    def __init__(
        self,
        name: str = "discord",
        bot_token: str | None = None,
        on_event: callable | None = None,
    ):
        super().__init__(name)
        self.bot_token = bot_token
        self._on_event = on_event
        self._pending_events: list[InboundEvent] = []
        self._client: discord.Client | None = None
        self._gateway_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.bot_token:
            logger.warning("No Discord bot token — channel disabled")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.members = True

        self._client = discord.Client(intents=intents)

        async def on_ready():
            if self._client and self._client.user:
                logger.info("Discord connected as %s (id=%s)", self._client.user.name, self._client.user.id)

        async def on_message(message):
            await self._handle_message(message)

        self._client.event(on_ready)
        self._client.event(on_message)

        self._gateway_task = asyncio.create_task(
            self._client.start(self.bot_token),
            name="discord-gateway",
        )

    async def stop(self) -> None:
        if self._client and not self._client.is_closed():
            await self._client.close()
        if self._gateway_task:
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except asyncio.CancelledError:
                pass

    async def poll(self) -> list[InboundEvent]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    async def _handle_message(self, message: discord.Message) -> None:
        if self._client and message.author.id == self._client.user.id:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self._client and self._client.user and self._client.user.mentioned_in(message)

        if is_dm:
            event_type = "dm"
        elif is_mention:
            event_type = "mention"
        else:
            event_type = "channel.message"

        guild_id = message.guild.id if message.guild else "DM"

        event = InboundEvent(
            channel="discord",
            event_type=event_type,
            payload={
                "content": message.content,
                "author": str(message.author),
                "author_id": str(message.author.id),
                "channel_id": str(message.channel.id),
                "guild_id": str(guild_id),
                "message_id": str(message.id),
                "attachments": [a.url for a in message.attachments],
            },
            raw_content=message.content,
            author=str(message.author),
            external_id=f"discord:msg:{message.id}",
            external_url=message.jump_url,
        )

        if self._on_event:
            await self._on_event(event)
        else:
            self._pending_events.append(event)

    def add_event(self, event: InboundEvent) -> None:
        self._pending_events.append(event)

"""Discord outbound: send messages, reactions, typing indicators."""

from __future__ import annotations

import asyncio

import discord


class DiscordSender:
    def __init__(self, client: discord.Client):
        self._client = client

    async def send_message(self, channel_id: int, content: str) -> None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        await channel.send(content)

    async def add_reaction(self, channel_id: int, message_id: int, emoji: str) -> None:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.add_reaction(emoji)

    async def start_typing(self, channel_id: int) -> asyncio.Task:
        channel = self._client.get_channel(channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(channel_id)

        async def _keep_typing():
            try:
                async with channel.typing():
                    await asyncio.sleep(120)
            except asyncio.CancelledError:
                pass

        return asyncio.create_task(_keep_typing())

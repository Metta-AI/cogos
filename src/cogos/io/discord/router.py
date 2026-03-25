"""Route inbound Discord messages to the correct cogent(s)."""

from __future__ import annotations

import logging
import re

import discord

from cogos.io.discord.lifecycle import ROLE_PREFIX, LifecycleManager

logger = logging.getLogger(__name__)


class MessageRouter:
    """Determine which cogent(s) should handle an inbound message."""

    def __init__(self, lifecycle: LifecycleManager):
        self._lifecycle = lifecycle
        self._last_interaction: dict[int, str] = {}  # user_id -> cogent_name
        self._thread_owners: dict[int, str] = {}  # thread_id -> cogent_name

    def update_last_interaction(self, user_id: int, cogent_name: str) -> None:
        self._last_interaction[user_id] = cogent_name

    def set_thread_owner(self, thread_id: int, cogent_name: str) -> None:
        self._thread_owners[thread_id] = cogent_name

    def route(self, message: discord.Message) -> list[str]:
        if isinstance(message.channel, discord.DMChannel):
            return self._route_dm(message)
        return self._route_guild(message)

    def _route_guild(self, message: discord.Message) -> list[str]:
        # 1. Role mentions
        mentioned = self._extract_role_mentions(message)
        if mentioned:
            for name in mentioned:
                self.update_last_interaction(message.author.id, name)
            return mentioned

        # 2. Thread ownership
        if isinstance(message.channel, discord.Thread):
            owner = self._thread_owners.get(message.channel.id)
            if owner:
                return [owner]

        # 3. Channel defaults
        channel_id = str(message.channel.id)
        for name, persona in self._lifecycle.personas.items():
            if channel_id in persona.default_channels:
                return [name]

        # 4. No match
        return []

    def _route_dm(self, message: discord.Message) -> list[str]:
        user_id = message.author.id

        # Check for switch intent
        switch_target = self._detect_switch(message.content)
        if switch_target:
            self.update_last_interaction(user_id, switch_target)
            return [switch_target]

        # Fall back to last interaction
        last = self._last_interaction.get(user_id)
        if last:
            return [last]

        return []

    def _extract_role_mentions(self, message: discord.Message) -> list[str]:
        results = []
        for role in message.role_mentions:
            if role.name.startswith(ROLE_PREFIX):
                cogent_name = role.name[len(ROLE_PREFIX):]
                if cogent_name in self._lifecycle.personas:
                    results.append(cogent_name)
        return results

    def _detect_switch(self, content: str) -> str | None:
        if not content:
            return None
        # Strip bot mentions (e.g. "<@123456>") from the start of the message
        lower = re.sub(r"<@!?\d+>\s*", "", content.strip()).lower()
        if not lower:
            return None
        for name in self._lifecycle.personas:
            nl = name.lower()
            # Exact match: "alpha"
            if lower == nl:
                return name
            # @-prefixed exact: "@alpha"
            if lower == f"@{nl}":
                return name
            # Name at start followed by separator (comma, space, etc.): "alpha, do X"
            if re.match(rf"@?{re.escape(nl)}[\s,:]", lower):
                return name
            if re.match(rf"switch\s+to\s+{re.escape(nl)}", lower, re.IGNORECASE):
                return name
        return None

    def available_cogents(self) -> list[str]:
        return list(self._lifecycle.personas.keys())

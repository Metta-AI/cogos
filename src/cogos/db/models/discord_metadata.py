"""Discord metadata models — guild and channel info synced by the bridge."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class DiscordGuild(BaseModel):
    guild_id: str
    cogent_name: str
    name: str
    icon_url: str | None = None
    member_count: int | None = None
    synced_at: datetime | None = None


class DiscordChannel(BaseModel):
    channel_id: str
    guild_id: str
    name: str
    topic: str | None = None
    category: str | None = None
    channel_type: str
    position: int = 0
    synced_at: datetime | None = None

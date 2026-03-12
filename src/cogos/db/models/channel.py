"""Channel model — typed append-only message stream."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelType(str, enum.Enum):
    IMPLICIT = "implicit"
    SPAWN = "spawn"
    NAMED = "named"


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    owner_process: UUID | None = None  # FK -> Process.id (None for system channels)
    schema_id: UUID | None = None  # FK -> Schema.id
    inline_schema: dict[str, Any] | None = None
    channel_type: ChannelType
    auto_close: bool = False
    closed_at: datetime | None = None
    created_at: datetime | None = None

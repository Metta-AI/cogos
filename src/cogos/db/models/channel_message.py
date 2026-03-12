"""ChannelMessage model — individual message in a channel."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChannelMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel: UUID  # FK -> Channel.id
    sender_process: UUID | None = None  # FK -> Process.id
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

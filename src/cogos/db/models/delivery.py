"""Delivery model — per-handler channel message delivery tracking."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DELIVERED = "delivered"
    SKIPPED = "skipped"


class Delivery(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    message: UUID  # FK -> ChannelMessage.id
    handler: UUID  # FK -> Handler.id
    status: DeliveryStatus = DeliveryStatus.PENDING
    run: UUID | None = None  # FK -> Run.id (which run processed this)
    created_at: datetime | None = None

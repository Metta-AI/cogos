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
    sender_run_id: UUID | None = None  # FK -> Run.id
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    trace_id: UUID | None = None
    trace_meta: dict[str, Any] | None = None
    created_at: datetime | None = None

"""Cron model — scheduled channel message emitter."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Cron(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    expression: str  # cron expression
    channel_name: str  # channel to send cron messages to
    payload: dict[str, Any] = Field(default_factory=dict)  # maps to DB column 'metadata'
    enabled: bool = True
    created_at: datetime | None = None

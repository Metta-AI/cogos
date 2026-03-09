"""Conversation model — multi-turn context routing."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    context_key: str = ""
    status: ConversationStatus = ConversationStatus.ACTIVE
    cli_session_id: str | None = None
    started_at: datetime | None = None
    last_active: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

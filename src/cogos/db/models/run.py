"""Run model — execution record for a single process invocation."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SUSPENDED = "suspended"


class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    process: UUID  # FK -> Process.id
    message: UUID | None = None  # FK -> ChannelMessage.id (triggering message)
    conversation: UUID | None = None  # FK -> Conversation.id
    status: RunStatus = RunStatus.RUNNING
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_ms: int | None = None
    error: str | None = None
    model_version: str | None = None
    result: dict[str, Any] | None = None  # validated against process.return_schema
    snapshot: dict[str, Any] | None = None  # conversation + scope for resume
    scope_log: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    completed_at: datetime | None = None

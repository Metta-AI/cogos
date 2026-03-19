"""Span models for distributed tracing."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SpanStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ERRORED = "errored"


class Span(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trace_id: UUID
    parent_span_id: UUID | None = None
    name: str
    coglet: str | None = None
    status: SpanStatus = SpanStatus.RUNNING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpanEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    span_id: UUID
    event: str  # "log", "error", "metric"
    message: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

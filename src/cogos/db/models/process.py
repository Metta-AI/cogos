"""Process model — the only active entity in CogOS."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProcessStatus(str, enum.Enum):
    WAITING = "waiting"
    RUNNABLE = "runnable"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    DISABLED = "disabled"


class ProcessMode(str, enum.Enum):
    DAEMON = "daemon"
    ONE_SHOT = "one_shot"


class Process(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    mode: ProcessMode = ProcessMode.ONE_SHOT
    content: str = ""
    priority: float = 0.0
    resources: list[UUID] = Field(default_factory=list)  # FK -> Resource
    runner: str = "lambda"  # "lambda" | "ecs"
    status: ProcessStatus = ProcessStatus.WAITING
    runnable_since: datetime | None = None
    parent_process: UUID | None = None  # FK -> Process.id
    preemptible: bool = False
    model: str | None = None
    model_constraints: dict[str, Any] = Field(default_factory=dict)
    return_schema: dict[str, Any] | None = None
    max_duration_ms: int | None = None
    max_retries: int = 0
    retry_count: int = 0
    retry_backoff_ms: int | None = None
    clear_context: bool = False  # ECS only: resume or fresh
    metadata: dict[str, Any] = Field(default_factory=dict)
    output_events: list[str] = Field(default_factory=list)  # event types this process emits
    schema_id: UUID | None = None  # FK -> Schema.id
    created_at: datetime | None = None
    updated_at: datetime | None = None

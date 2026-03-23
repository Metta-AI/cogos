"""Executor and ExecutorToken models — channel-based persistent executors."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ExecutorStatus(str, enum.Enum):
    IDLE = "idle"
    BUSY = "busy"
    STALE = "stale"
    DEAD = "dead"


class Executor(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    executor_id: str  # human-readable ID, e.g. "executor-fargate-a1b2c3d4"
    channel_type: str = "claude-code"
    executor_tags: list[str] = Field(default_factory=list)
    dispatch_type: str = "channel"  # "channel" | "lambda"
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: ExecutorStatus = ExecutorStatus.IDLE
    current_run_id: UUID | None = None
    last_heartbeat_at: datetime | None = None
    registered_at: datetime | None = None


class ExecutorToken(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    token_hash: str  # SHA-256 of bearer token
    token_raw: str = ""  # raw token stored for local dev (build launch commands)
    scope: str = "executor"
    created_at: datetime | None = None
    revoked_at: datetime | None = None

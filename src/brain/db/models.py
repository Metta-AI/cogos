"""Pydantic models for all brain database tables."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# --- Enums ---


class MemoryScope(str, enum.Enum):
    POLIS = "polis"
    COGENT = "cogent"


class MemoryType(str, enum.Enum):
    FACT = "fact"
    EPISODIC = "episodic"
    PROMPT = "prompt"
    POLICY = "policy"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ConversationStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


class ChannelType(str, enum.Enum):
    DISCORD = "discord"
    GITHUB = "github"
    EMAIL = "email"
    ASANA = "asana"
    CLI = "cli"


class AlertSeverity(str, enum.Enum):
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class BudgetPeriod(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ProgramType(str, enum.Enum):
    PROMPT = "prompt"
    PYTHON = "python"


# --- Core Models ---


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scope: MemoryScope
    type: MemoryType
    name: str | None = None
    content: str = ""
    embedding: list[float] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Program(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    program_type: ProgramType = ProgramType.PROMPT
    content: str = ""
    includes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: ChannelType
    name: str
    external_id: str | None = None
    secret_arn: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime | None = None


# --- Work Models ---


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    parent_task_id: UUID | None = None
    creator: str = ""
    source_event: str | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    context_key: str = ""
    channel_id: UUID | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    cli_session_id: str | None = None
    started_at: datetime | None = None
    last_active: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    program_name: str
    task_id: UUID | None = None
    trigger_id: UUID | None = None
    conversation_id: UUID | None = None
    status: RunStatus = RunStatus.RUNNING
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_ms: int | None = None
    events_emitted: list[str] = Field(default_factory=list)
    error: str | None = None
    model_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Trace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    memory_ops: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str | None = None
    created_at: datetime | None = None


# --- Infrastructure Models ---


class Event(BaseModel):
    id: int | None = None
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_event_id: int | None = None
    created_at: datetime | None = None


class Alert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    severity: AlertSeverity
    alert_type: str
    source: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None


class Budget(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    period: BudgetPeriod
    period_start: date
    tokens_spent: int = 0
    cost_spent_usd: Decimal = Decimal("0")
    token_limit: int = 0
    cost_limit_usd: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Trigger & Cron Models ---


class TriggerConfig(BaseModel):
    retry_max_attempts: int = 1
    retry_backoff: Literal["none", "linear", "exponential"] = "none"
    retry_backoff_base_seconds: float = 5.0
    on_failure: str | None = None


class Trigger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    program_name: str
    event_pattern: str
    priority: int = 10
    config: TriggerConfig = Field(default_factory=TriggerConfig)
    enabled: bool = True
    created_at: datetime | None = None


class Cron(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cron_expression: str
    event_pattern: str
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

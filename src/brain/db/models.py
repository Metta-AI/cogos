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
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionStatus(str, enum.Enum):
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


class TriggerType(str, enum.Enum):
    EVENT = "event"
    CRON = "cron"


# --- Core Models ---


class MemoryRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    scope: MemoryScope
    type: MemoryType
    name: str | None = None
    content: str = ""
    embedding: list[float] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Skill(BaseModel):
    cogent_id: str
    name: str
    skill_type: str = "markdown"
    source: str = "golden"
    description: str = ""
    content: str = ""
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)
    sla: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Channel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
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
    cogent_id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PROPOSED
    priority: int = 0
    source: str = "agent"
    channel_id: UUID | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    context_key: str = ""
    channel_id: UUID | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    cli_session_id: str | None = None
    started_at: datetime | None = None
    last_active: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Execution(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    skill_name: str
    trigger_id: UUID | None = None
    conversation_id: UUID | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: Decimal = Decimal("0")
    duration_ms: int | None = None
    events_emitted: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Trace(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    execution_id: UUID
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    memory_ops: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str | None = None
    created_at: datetime | None = None


# --- Infrastructure Models ---


class Event(BaseModel):
    id: int | None = None
    cogent_id: str
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_event_id: int | None = None
    created_at: datetime | None = None


class Alert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
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
    cogent_id: str
    period: BudgetPeriod
    period_start: date
    tokens_spent: int = 0
    cost_spent_usd: Decimal = Decimal("0")
    token_limit: int = 0
    cost_limit_usd: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Trigger Models (consolidated from mind/models.py) ---


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff: Literal["none", "linear", "exponential"] = "none"
    backoff_base_seconds: float = 5.0


class TriggerConfig(BaseModel):
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_failure: str | None = None
    context_key_template: str | None = None


class Trigger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cogent_id: str
    trigger_type: TriggerType = TriggerType.EVENT
    event_pattern: str = ""
    cron_expression: str = ""
    skill_name: str = ""
    priority: int = 10
    config: TriggerConfig = Field(default_factory=TriggerConfig)
    enabled: bool = True
    created_at: datetime | None = None

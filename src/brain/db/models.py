"""Pydantic models for all brain database tables."""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# --- Enums ---


class TaskStatus(str, enum.Enum):
    RUNNABLE = "runnable"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    DISABLED = "disabled"


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


def infer_program_type(content: str) -> ProgramType:
    """Infer program type from content. Python if it has a def run() function."""
    import ast
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run":
                return ProgramType.PYTHON
    except SyntaxError:
        pass
    return ProgramType.PROMPT


# --- Core Models ---


class MemoryVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_id: UUID
    version: int
    read_only: bool = False
    content: str = ""
    source: str = "cogent"
    created_at: datetime | None = None


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    active_version: int = 1
    includes: list[str] = Field(default_factory=list)
    versions: dict[int, MemoryVersion] = Field(default_factory=dict)
    created_at: datetime | None = None
    modified_at: datetime | None = None


class Program(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    memory_id: UUID | None = None
    memory_version: int | None = None
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    runner: str | None = None
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
    program_name: str = "vsm/s1/do-content"
    content: str = ""
    memory_keys: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.RUNNABLE
    priority: float = 0.0
    runner: str | None = None
    clear_context: bool = False
    recurrent: bool = False
    resources: list[str] = Field(default_factory=list)
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
    status: str = "proposed"
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
    max_events: int = 0  # 0 = no throttle
    throttle_window_seconds: int = 60


class Trigger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    program_name: str
    event_pattern: str
    priority: int = 10
    config: TriggerConfig = Field(default_factory=TriggerConfig)
    enabled: bool = True
    throttle_timestamps: list[float] = Field(default_factory=list)
    throttle_rejected: int = 0
    throttle_active: bool = False
    created_at: datetime | None = None


class ThrottleResult(BaseModel):
    allowed: bool
    state_changed: bool
    throttle_active: bool


class Cron(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    cron_expression: str
    event_pattern: str
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class Tool(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = ""  # hierarchical, e.g. "mind/task/create"; set by loader
    description: str = ""
    instructions: str = ""  # usage guidance injected into search_tools results
    input_schema: dict[str, Any] = Field(default_factory=dict)
    handler: str = ""  # Python dotted path, e.g. "channels.gmail.tools:gmail_check"
    iam_role_arn: str | None = None  # optional IAM role for scoped access
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResourceType(str, enum.Enum):
    POOL = "pool"
    CONSUMABLE = "consumable"


class Resource(BaseModel):
    name: str
    resource_type: ResourceType = ResourceType.POOL
    capacity: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ResourceUsage(BaseModel):
    id: int | None = None
    resource_name: str
    run_id: UUID
    amount: float
    created_at: datetime | None = None

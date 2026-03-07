from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StatusResponse(BaseModel):
    cogent_name: str
    active_sessions: int = 0
    total_conversations: int = 0
    trigger_count: int = 0
    unresolved_alerts: int = 0
    recent_events: int = 0


class Execution(BaseModel):
    id: str
    program_name: str
    conversation_id: str | None = None
    status: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_usd: float = 0
    error: str | None = None


class Program(BaseModel):
    name: str
    type: str = "prompt"
    description: str = ""
    trigger_count: int = 0
    runs: int = 0
    ok: int = 0
    fail: int = 0
    total_cost: float = 0
    last_run: str | None = None


class ProgramsResponse(BaseModel):
    cogent_name: str
    count: int
    programs: list[Program]


class ExecutionsResponse(BaseModel):
    cogent_name: str
    count: int
    executions: list[Execution]


class Session(BaseModel):
    id: str
    context_key: str | None = None
    status: str | None = None
    cli_session_id: str | None = None
    started_at: str | None = None
    last_active: str | None = None
    metadata: dict[str, Any] | None = None
    runs: int = 0
    ok: int = 0
    fail: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    total_cost: float = 0


class SessionsResponse(BaseModel):
    cogent_name: str
    count: int
    sessions: list[Session]


class Event(BaseModel):
    id: int | str
    event_type: str | None = None
    source: str | None = None
    payload: Any = None
    parent_event_id: int | None = None
    created_at: str | None = None


class EventsResponse(BaseModel):
    cogent_name: str
    count: int
    events: list[Event]


class EventTreeResponse(BaseModel):
    root_event_id: int | str | None = None
    count: int
    events: list[Event]


class Trigger(BaseModel):
    id: str
    name: str = ""
    event_pattern: str | None = None
    program_name: str | None = None
    priority: int | None = None
    enabled: bool = True
    created_at: str | None = None
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0


class TriggersResponse(BaseModel):
    cogent_name: str
    count: int
    triggers: list[Trigger]


class TriggerCreate(BaseModel):
    program_name: str
    event_pattern: str
    priority: int = 10
    enabled: bool = True
    metadata: dict[str, Any] = {}


class TriggerUpdate(BaseModel):
    program_name: str | None = None
    event_pattern: str | None = None
    priority: int | None = None


class ToggleRequest(BaseModel):
    ids: list[str]
    enabled: bool


class ToggleResponse(BaseModel):
    updated: int
    enabled: bool


class MemoryVersionItem(BaseModel):
    id: str
    version: int
    content: str = ""
    source: str = "cogent"
    read_only: bool = False
    created_at: str | None = None


class MemoryItem(BaseModel):
    id: str
    name: str = ""
    group: str = ""
    active_version: int = 1
    content: str = ""
    source: str = "cogent"
    read_only: bool = False
    created_at: str | None = None
    modified_at: str | None = None
    versions: list[MemoryVersionItem] = []


class MemoryCreate(BaseModel):
    name: str
    content: str = ""
    source: str = "cogent"
    read_only: bool = False


class MemoryUpdate(BaseModel):
    content: str | None = None
    source: str | None = None
    read_only: bool | None = None


class MemoryResponse(BaseModel):
    cogent_name: str
    count: int
    memory: list[MemoryItem]


class Task(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    program_name: str | None = None
    content: str | None = None
    status: str | None = None
    priority: float | None = None
    runner: str | None = None
    clear_context: bool | None = None
    recurrent: bool | None = None
    memory_keys: list[str] | None = None
    tools: list[str] | None = None
    resources: list[str] | None = None
    creator: str | None = None
    parent_task_id: str | None = None
    source_event: str | None = None
    limits: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    last_run_status: str | None = None
    last_run_error: str | None = None
    last_run_at: str | None = None
    run_counts: dict[str, dict[str, int]] | None = None


class TaskCreate(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    program_name: str = "vsm/s1/do-content"
    status: str = "runnable"
    priority: float = 0.0
    runner: str | None = None
    clear_context: bool = False
    recurrent: bool = False
    memory_keys: list[str] | None = None
    tools: list[str] | None = None
    resources: list[str] | None = None
    creator: str = "dashboard"
    source_event: str | None = None
    limits: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    program_name: str | None = None
    status: str | None = None
    priority: float | None = None
    runner: str | None = None
    clear_context: bool | None = None
    recurrent: bool | None = None
    memory_keys: list[str] | None = None
    tools: list[str] | None = None
    resources: list[str] | None = None
    creator: str | None = None
    source_event: str | None = None
    limits: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class TasksResponse(BaseModel):
    cogent_name: str
    count: int
    tasks: list[Task]


class Channel(BaseModel):
    name: str
    type: str | None = None
    enabled: bool = True
    created_at: str | None = None


class ChannelCreate(BaseModel):
    name: str
    type: str = "cli"
    enabled: bool = True
    config: dict[str, Any] = {}


class ChannelUpdate(BaseModel):
    type: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ChannelsResponse(BaseModel):
    cogent_name: str
    count: int
    channels: list[Channel]


class Alert(BaseModel):
    id: str
    severity: str | None = None
    alert_type: str | None = None
    source: str | None = None
    message: str | None = None
    metadata: dict[str, Any] | None = None
    resolved_at: str | None = None
    created_at: str | None = None


class AlertCreate(BaseModel):
    severity: str = "warning"
    alert_type: str = ""
    source: str = ""
    message: str
    metadata: dict[str, Any] = {}


class AlertsResponse(BaseModel):
    cogent_name: str
    count: int
    alerts: list[Alert]


class CronItem(BaseModel):
    id: str
    cron_expression: str
    event_pattern: str
    enabled: bool = True
    metadata: dict[str, Any] = {}
    created_at: str | None = None


class CronCreate(BaseModel):
    cron_expression: str
    event_pattern: str
    enabled: bool = True
    metadata: dict[str, Any] = {}


class CronUpdate(BaseModel):
    cron_expression: str | None = None
    event_pattern: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class CronsResponse(BaseModel):
    cogent_name: str
    count: int
    crons: list[CronItem]


class ResourceItem(BaseModel):
    name: str
    resource_type: str = "pool"
    capacity: float = 1.0
    used: float = 0.0
    metadata: dict[str, Any] = {}
    created_at: str | None = None


class ResourcesResponse(BaseModel):
    cogent_name: str
    count: int = 0
    resources: list[ResourceItem] = []

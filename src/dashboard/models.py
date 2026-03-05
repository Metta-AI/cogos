from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StatusResponse(BaseModel):
    cogent_id: str
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
    type: str = "markdown"
    description: str = ""
    complexity: str | None = None
    model: str | None = None
    trigger_count: int = 0
    group: str = ""
    runs: int = 0
    ok: int = 0
    fail: int = 0
    total_cost: float = 0
    last_run: str | None = None


class ProgramsResponse(BaseModel):
    cogent_id: str
    count: int
    programs: list[Program]


class ExecutionsResponse(BaseModel):
    cogent_id: str
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
    cogent_id: str
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
    cogent_id: str
    count: int
    events: list[Event]


class EventTreeResponse(BaseModel):
    root_event_id: int | str | None = None
    count: int
    events: list[Event]


class Trigger(BaseModel):
    id: str
    name: str = ""
    trigger_type: str | None = None
    event_pattern: str | None = None
    cron_expression: str | None = None
    program_name: str | None = None
    priority: int | None = None
    enabled: bool = True
    created_at: str | None = None
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0


class TriggersResponse(BaseModel):
    cogent_id: str
    count: int
    triggers: list[Trigger]


class ToggleRequest(BaseModel):
    ids: list[str]
    enabled: bool


class ToggleResponse(BaseModel):
    updated: int
    enabled: bool


class MemoryItem(BaseModel):
    id: str
    scope: str | None = None
    type: str | None = None
    name: str = ""
    group: str = ""
    content: str = ""
    provenance: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryResponse(BaseModel):
    cogent_id: str
    count: int
    memory: list[MemoryItem]


class Task(BaseModel):
    id: str
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    source: str | None = None
    external_id: str | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class TasksResponse(BaseModel):
    cogent_id: str
    count: int
    tasks: list[Task]


class Channel(BaseModel):
    name: str
    type: str | None = None
    enabled: bool = True
    created_at: str | None = None


class ChannelsResponse(BaseModel):
    cogent_id: str
    count: int
    channels: list[Channel]


class Alert(BaseModel):
    id: str
    severity: str | None = None
    alert_type: str | None = None
    source: str | None = None
    message: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


class AlertsResponse(BaseModel):
    cogent_id: str
    count: int
    alerts: list[Alert]


class ResourcesResponse(BaseModel):
    cogent_id: str
    active_sessions: int = 0
    conversations: list[dict[str, Any]] = []

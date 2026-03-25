from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StatusResponse(BaseModel):
    cogent_name: str
    active_sessions: int = 0
    total_conversations: int = 0
    trigger_count: int = 0
    unresolved_alerts: int = 0


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


class Trigger(BaseModel):
    id: str
    name: str = ""
    channel_pattern: str | None = None
    program_name: str | None = None
    priority: int | None = None
    enabled: bool = True
    created_at: str | None = None
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0
    max_events: int = 0
    throttle_window_seconds: int = 60
    throttle_rejected: int = 0
    throttle_active: bool = False


class TriggersResponse(BaseModel):
    cogent_name: str
    count: int
    triggers: list[Trigger]


class TriggerCreate(BaseModel):
    program_name: str
    channel_pattern: str
    priority: int = 10
    enabled: bool = True
    metadata: dict[str, Any] = {}
    max_events: int = 0
    throttle_window_seconds: int = 60


class TriggerUpdate(BaseModel):
    program_name: str | None = None
    channel_pattern: str | None = None
    priority: int | None = None
    max_events: int | None = None
    throttle_window_seconds: int | None = None


class ToggleRequest(BaseModel):
    ids: list[str]
    enabled: bool


class ToggleResponse(BaseModel):
    updated: int
    enabled: bool


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
    channel_name: str
    enabled: bool = True
    metadata: dict[str, Any] = {}
    created_at: str | None = None


class CronCreate(BaseModel):
    cron_expression: str
    channel_name: str
    enabled: bool = True
    metadata: dict[str, Any] = {}


class CronUpdate(BaseModel):
    cron_expression: str | None = None
    channel_name: str | None = None
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


class ToolItem(BaseModel):
    id: str
    name: str
    description: str = ""
    instructions: str = ""
    input_schema: dict[str, Any] = {}
    handler: str = ""
    iam_role_arn: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = {}
    created_at: str | None = None
    updated_at: str | None = None


class ToolsResponse(BaseModel):
    cogent_name: str
    count: int
    tools: list[ToolItem]


class ToolUpdate(BaseModel):
    description: str | None = None
    instructions: str | None = None
    input_schema: dict[str, Any] | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None

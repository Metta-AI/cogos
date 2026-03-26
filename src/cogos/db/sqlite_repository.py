from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

from cogos.db.models import (
    ALL_EPOCHS,
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    CogosOperation,
    Cron,
    Delivery,
    DeliveryStatus,
    Executor,
    ExecutorStatus,
    ExecutorToken,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    Run,
    RunStatus,
    Schema,
    Span,
    SpanEvent,
    SpanStatus,
    Trace,
)
from cogos.db.models.alert import Alert
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild
from cogos.db.models.trace import RequestTrace
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType

logger = logging.getLogger(__name__)


def _json_serial(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cogos_file (
    id          TEXT PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    includes    TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_file_version (
    id          TEXT PRIMARY KEY,
    file_id     TEXT NOT NULL REFERENCES cogos_file(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    read_only   INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'cogent',
    is_active   INTEGER NOT NULL DEFAULT 1,
    run_id      TEXT,
    created_at  TEXT,
    UNIQUE (file_id, version)
);

CREATE TABLE IF NOT EXISTS cogos_capability (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    instructions    TEXT NOT NULL DEFAULT '',
    handler         TEXT NOT NULL DEFAULT '',
    schema          TEXT NOT NULL DEFAULT '{}',
    iam_role_arn    TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    metadata        TEXT NOT NULL DEFAULT '{}',
    event_types     TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_process (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    mode                TEXT NOT NULL DEFAULT 'one_shot',
    content             TEXT NOT NULL DEFAULT '',
    priority            REAL NOT NULL DEFAULT 0.0,
    resources           TEXT NOT NULL DEFAULT '[]',
    required_tags       TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL DEFAULT 'waiting'
                        CHECK (status IN ('waiting', 'runnable',
                                          'blocked', 'suspended', 'disabled')),
    runnable_since      TEXT,
    parent_process      TEXT REFERENCES cogos_process(id),
    preemptible         INTEGER NOT NULL DEFAULT 0,
    model               TEXT,
    model_constraints   TEXT NOT NULL DEFAULT '{}',
    return_schema       TEXT,
    idle_timeout_ms     INTEGER,
    max_duration_ms     INTEGER,
    max_retries         INTEGER NOT NULL DEFAULT 0,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    retry_backoff_ms    INTEGER,
    clear_context       INTEGER NOT NULL DEFAULT 0,
    metadata            TEXT NOT NULL DEFAULT '{}',
    output_events       TEXT NOT NULL DEFAULT '[]',
    epoch               INTEGER NOT NULL DEFAULT 0,
    tty                 INTEGER NOT NULL DEFAULT 0,
    executor            TEXT NOT NULL DEFAULT 'llm',
    schema_id           TEXT,
    created_at          TEXT,
    updated_at          TEXT,
    UNIQUE (name, epoch)
);

CREATE TABLE IF NOT EXISTS cogos_process_capability (
    id          TEXT PRIMARY KEY,
    process     TEXT NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    capability  TEXT NOT NULL REFERENCES cogos_capability(id) ON DELETE CASCADE,
    name        TEXT NOT NULL DEFAULT '',
    epoch       INTEGER NOT NULL DEFAULT 0,
    config      TEXT NOT NULL DEFAULT '{}',
    UNIQUE (process, name)
);

CREATE TABLE IF NOT EXISTS cogos_handler (
    id              TEXT PRIMARY KEY,
    process         TEXT NOT NULL REFERENCES cogos_process(id) ON DELETE CASCADE,
    channel         TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1,
    epoch           INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    UNIQUE (process, channel)
);

CREATE TABLE IF NOT EXISTS cogos_delivery (
    id          TEXT PRIMARY KEY,
    message     TEXT NOT NULL,
    handler     TEXT NOT NULL REFERENCES cogos_handler(id) ON DELETE CASCADE,
    trace_id    TEXT,
    epoch       INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'queued', 'delivered', 'skipped')),
    run         TEXT,
    created_at  TEXT,
    UNIQUE (message, handler)
);

CREATE TABLE IF NOT EXISTS cogos_cron (
    id              TEXT PRIMARY KEY,
    expression      TEXT NOT NULL,
    channel_name    TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_run        TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_channel (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    channel_type    TEXT NOT NULL DEFAULT 'implicit',
    owner_process   TEXT,
    schema_id       TEXT,
    inline_schema   TEXT,
    auto_close      INTEGER NOT NULL DEFAULT 0,
    closed_at       TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_channel_message (
    id                  TEXT PRIMARY KEY,
    channel             TEXT NOT NULL REFERENCES cogos_channel(id) ON DELETE CASCADE,
    sender_process      TEXT,
    sender_run_id       TEXT,
    payload             TEXT NOT NULL DEFAULT '{}',
    idempotency_key     TEXT,
    trace_id            TEXT,
    trace_meta          TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS cogos_schema (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    definition  TEXT NOT NULL DEFAULT '{}',
    file_id     TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_run (
    id              TEXT PRIMARY KEY,
    process         TEXT NOT NULL REFERENCES cogos_process(id),
    message         TEXT,
    conversation    TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'failed', 'timeout', 'suspended', 'throttled')),
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        TEXT NOT NULL DEFAULT '0',
    duration_ms     INTEGER,
    error           TEXT,
    model_version   TEXT,
    result          TEXT,
    snapshot        TEXT,
    scope_log       TEXT NOT NULL DEFAULT '[]',
    epoch           INTEGER NOT NULL DEFAULT 0,
    trace_id        TEXT,
    parent_trace_id TEXT,
    metadata        TEXT,
    created_at      TEXT,
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS cogos_trace (
    id                  TEXT PRIMARY KEY,
    run                 TEXT NOT NULL REFERENCES cogos_run(id) ON DELETE CASCADE,
    capability_calls    TEXT NOT NULL DEFAULT '[]',
    file_ops            TEXT NOT NULL DEFAULT '[]',
    model_version       TEXT,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS cogos_request_trace (
    id          TEXT PRIMARY KEY,
    cogent_id   TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    source_ref  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_span (
    id              TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    name            TEXT NOT NULL,
    coglet          TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    metadata        TEXT NOT NULL DEFAULT '{}',
    started_at      TEXT,
    ended_at        TEXT
);

CREATE TABLE IF NOT EXISTS cogos_span_event (
    id          TEXT PRIMARY KEY,
    span_id     TEXT NOT NULL REFERENCES cogos_span(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    message     TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    timestamp   TEXT
);

CREATE TABLE IF NOT EXISTS cogos_resource (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    resource_type   TEXT NOT NULL DEFAULT 'pool',
    capacity        REAL NOT NULL DEFAULT 1.0,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_operation (
    id          TEXT PRIMARY KEY,
    epoch       INTEGER NOT NULL DEFAULT 0,
    type        TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_executor (
    id              TEXT PRIMARY KEY,
    executor_id     TEXT NOT NULL UNIQUE,
    channel_type    TEXT NOT NULL DEFAULT 'claude-code',
    executor_tags   TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'idle',
    current_run_id  TEXT,
    dispatch_type   TEXT NOT NULL DEFAULT 'channel',
    metadata        TEXT NOT NULL DEFAULT '{}',
    last_heartbeat_at TEXT,
    registered_at   TEXT
);

CREATE TABLE IF NOT EXISTS cogos_executor_token (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    token_hash  TEXT NOT NULL UNIQUE,
    token_raw   TEXT NOT NULL DEFAULT '',
    scope       TEXT NOT NULL DEFAULT 'executor',
    created_at  TEXT,
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS cogos_alert (
    id              TEXT PRIMARY KEY,
    severity        TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    source          TEXT NOT NULL,
    message         TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}',
    acknowledged_at TEXT,
    resolved_at     TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS cogos_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cogos_discord_guild (
    guild_id        TEXT PRIMARY KEY,
    cogent_name     TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    icon_url        TEXT,
    member_count    INTEGER,
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS cogos_discord_channel (
    channel_id      TEXT PRIMARY KEY,
    guild_id        TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    topic           TEXT,
    category        TEXT,
    channel_type    TEXT NOT NULL DEFAULT '',
    position        INTEGER NOT NULL DEFAULT 0,
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS cogos_wait_condition (
    id          TEXT PRIMARY KEY,
    run         TEXT,
    process     TEXT,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    pending     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS cogos_epoch (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    epoch   INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO cogos_epoch (id, epoch) VALUES (1, 0);
"""


class SqliteRepository:

    def __init__(
        self,
        data_dir: str,
        *,
        ingress_queue_url: str = "",
        nudge_callback: Any = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "cogos.db"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.create_function(
            "regexp", 2, lambda pattern, string: bool(re.search(pattern, string if string is not None else "")),
        )
        self._conn.executescript(_SCHEMA_SQL)
        self._ingress_queue_url = ingress_queue_url
        self._nudge_callback = nudge_callback
        self._batch_depth = 0

    # ── Internal helpers ──────────────────────────────────────

    def _execute(self, sql: str, params: dict[str, Any] | tuple | None = None) -> int:
        cur = self._conn.execute(sql, params or {})
        if self._batch_depth == 0:
            self._conn.commit()
        return cur.rowcount

    def _query(self, sql: str, params: dict[str, Any] | tuple | None = None) -> list[dict]:
        cur = self._conn.execute(sql, params or {})
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def _query_one(self, sql: str, params: dict[str, Any] | tuple | None = None) -> dict | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return self._query(sql, params)

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return self._execute(sql, params)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _json_dumps(self, obj: Any) -> str:
        return json.dumps(obj, default=_json_serial)

    def _json_loads(self, s: str | None) -> Any:
        if s is None:
            return None
        return json.loads(s)

    def _json_loads_dict(self, s: str | None) -> dict:
        """Load JSON that must be a dict. Asserts type correctness."""
        if s is None:
            return {}
        result = json.loads(s)
        assert isinstance(result, dict), f"Expected dict from JSON, got {type(result).__name__}"
        return result

    def _json_loads_list(self, s: str | None) -> list:
        """Load JSON that must be a list. Asserts type correctness."""
        if s is None:
            return []
        result = json.loads(s)
        assert isinstance(result, list), f"Expected list from JSON, got {type(result).__name__}"
        return result

    # ── Nudge ─────────────────────────────────────────────────

    def _nudge_ingress(self, *, process_id: UUID | None = None) -> None:
        if not self._ingress_queue_url:
            return
        if self._nudge_callback is None:
            return
        try:
            import json as _json

            body: dict = {"source": "channel_message"}
            if process_id is not None:
                body["process_id"] = str(process_id)
            self._nudge_callback(
                self._ingress_queue_url,
                _json.dumps(body),
            )
        except Exception:
            logger.debug("Failed to nudge ingress queue", exc_info=True)

    # ── Row converters ───────────────────────────────────────

    def _parse_uuid(self, val: str | None) -> UUID | None:
        if val is None:
            return None
        return UUID(val)

    def _parse_dt(self, val: str | None) -> datetime | None:
        if val is None:
            return None
        return datetime.fromisoformat(val)

    def _row_to_process(self, row: dict) -> Process:
        return Process(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            name=row["name"],
            mode=ProcessMode(row["mode"]),
            content=row["content"],
            priority=row["priority"],
            resources=self._json_loads_list(row["resources"]),
            required_tags=self._json_loads_list(row["required_tags"]),
            executor=row["executor"],
            status=ProcessStatus(row["status"]),
            runnable_since=self._parse_dt(row.get("runnable_since")),
            parent_process=self._parse_uuid(row.get("parent_process")),
            preemptible=bool(row["preemptible"]),
            model=row.get("model"),
            model_constraints=self._json_loads_dict(row["model_constraints"]),
            return_schema=self._json_loads(row.get("return_schema")),
            idle_timeout_ms=row.get("idle_timeout_ms"),
            max_duration_ms=row.get("max_duration_ms"),
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            retry_backoff_ms=row.get("retry_backoff_ms"),
            clear_context=bool(row["clear_context"]),
            tty=bool(row["tty"]),
            metadata=self._json_loads_dict(row["metadata"]),
            output_events=self._json_loads_list(row["output_events"]),
            schema_id=self._parse_uuid(row.get("schema_id")),
            created_at=self._parse_dt(row.get("created_at")),
            updated_at=self._parse_dt(row.get("updated_at")),
        )

    def _row_to_capability(self, row: dict) -> Capability:
        return Capability(
            id=UUID(row["id"]),
            name=row["name"],
            description=row["description"],
            instructions=row["instructions"],
            handler=row["handler"],
            schema=self._json_loads_dict(row["schema"]),
            iam_role_arn=row.get("iam_role_arn"),
            enabled=bool(row["enabled"]),
            metadata=self._json_loads_dict(row["metadata"]),
            created_at=self._parse_dt(row.get("created_at")),
            updated_at=self._parse_dt(row.get("updated_at")),
        )

    def _row_to_handler(self, row: dict) -> Handler:
        return Handler(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            process=UUID(row["process"]),
            channel=self._parse_uuid(row.get("channel")),
            enabled=bool(row["enabled"]),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_process_capability(self, row: dict) -> ProcessCapability:
        return ProcessCapability(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            process=UUID(row["process"]),
            capability=UUID(row["capability"]),
            name=row["name"],
            config=self._json_loads(row.get("config")),
        )

    def _row_to_file(self, row: dict) -> File:
        return File(
            id=UUID(row["id"]),
            key=row["key"],
            includes=self._json_loads_list(row["includes"]),
            created_at=self._parse_dt(row.get("created_at")),
            updated_at=self._parse_dt(row.get("updated_at")),
        )

    def _row_to_file_version(self, row: dict) -> FileVersion:
        return FileVersion(
            id=UUID(row["id"]),
            file_id=UUID(row["file_id"]),
            version=row["version"],
            read_only=bool(row["read_only"]),
            content=row["content"],
            source=row["source"],
            is_active=bool(row["is_active"]),
            run_id=self._parse_uuid(row.get("run_id")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_resource(self, row: dict) -> Resource:
        return Resource(
            id=UUID(row["id"]),
            name=row["name"],
            resource_type=ResourceType(row["resource_type"]),
            capacity=row["capacity"],
            metadata=self._json_loads_dict(row["metadata"]),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_cron(self, row: dict) -> Cron:
        return Cron(
            id=UUID(row["id"]),
            expression=row["expression"],
            channel_name=row["channel_name"],
            payload=self._json_loads_dict(row["payload"]),
            enabled=bool(row["enabled"]),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_delivery(self, row: dict) -> Delivery:
        return Delivery(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            message=UUID(row["message"]),
            handler=UUID(row["handler"]),
            status=DeliveryStatus(row["status"]),
            run=self._parse_uuid(row.get("run")),
            trace_id=self._parse_uuid(row.get("trace_id")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_run(self, row: dict) -> Run:
        return Run(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            process=UUID(row["process"]),
            message=self._parse_uuid(row.get("message")),
            conversation=self._parse_uuid(row.get("conversation")),
            status=RunStatus(row["status"]),
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            cost_usd=Decimal(row["cost_usd"]),
            duration_ms=row.get("duration_ms"),
            error=row.get("error"),
            model_version=row.get("model_version"),
            result=self._json_loads(row.get("result")),
            snapshot=self._json_loads(row.get("snapshot")),
            scope_log=self._json_loads_list(row["scope_log"]),
            trace_id=self._parse_uuid(row.get("trace_id")),
            parent_trace_id=self._parse_uuid(row.get("parent_trace_id")),
            metadata=self._json_loads(row.get("metadata")),
            created_at=self._parse_dt(row.get("created_at")),
            completed_at=self._parse_dt(row.get("completed_at")),
        )

    def _row_to_schema(self, row: dict) -> Schema:
        return Schema(
            id=UUID(row["id"]),
            name=row["name"],
            definition=self._json_loads_dict(row["definition"]),
            file_id=self._parse_uuid(row.get("file_id")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_channel(self, row: dict) -> Channel:
        return Channel(
            id=UUID(row["id"]),
            name=row["name"],
            owner_process=self._parse_uuid(row.get("owner_process")),
            schema_id=self._parse_uuid(row.get("schema_id")),
            inline_schema=self._json_loads(row.get("inline_schema")),
            channel_type=ChannelType(row["channel_type"]),
            auto_close=bool(row["auto_close"]),
            closed_at=self._parse_dt(row.get("closed_at")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_channel_message(self, row: dict) -> ChannelMessage:
        return ChannelMessage(
            id=UUID(row["id"]),
            channel=UUID(row["channel"]),
            sender_process=self._parse_uuid(row.get("sender_process")),
            payload=self._json_loads_dict(row["payload"]),
            idempotency_key=row.get("idempotency_key"),
            trace_id=self._parse_uuid(row.get("trace_id")),
            trace_meta=self._json_loads(row.get("trace_meta")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_discord_guild(self, row: dict) -> DiscordGuild:
        return DiscordGuild(
            guild_id=row["guild_id"],
            cogent_name=row["cogent_name"],
            name=row["name"],
            icon_url=row.get("icon_url"),
            member_count=row.get("member_count"),
            synced_at=self._parse_dt(row.get("synced_at")),
        )

    def _row_to_discord_channel(self, row: dict) -> DiscordChannel:
        return DiscordChannel(
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            name=row["name"],
            topic=row.get("topic"),
            category=row.get("category"),
            channel_type=row["channel_type"],
            position=row["position"],
            synced_at=self._parse_dt(row.get("synced_at")),
        )

    def _row_to_operation(self, row: dict) -> CogosOperation:
        return CogosOperation(
            id=UUID(row["id"]),
            epoch=row["epoch"],
            type=row["type"],
            metadata=self._json_loads_dict(row["metadata"]),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_request_trace(self, row: dict) -> RequestTrace:
        return RequestTrace(
            id=UUID(row["id"]),
            cogent_id=row["cogent_id"],
            source=row["source"],
            source_ref=row.get("source_ref"),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_span(self, row: dict) -> Span:
        return Span(
            id=UUID(row["id"]),
            trace_id=UUID(row["trace_id"]),
            parent_span_id=self._parse_uuid(row.get("parent_span_id")),
            name=row["name"],
            coglet=row.get("coglet"),
            status=SpanStatus(row["status"]),
            metadata=self._json_loads_dict(row["metadata"]),
            started_at=self._parse_dt(row.get("started_at")),
            ended_at=self._parse_dt(row.get("ended_at")),
        )

    def _row_to_span_event(self, row: dict) -> SpanEvent:
        return SpanEvent(
            id=UUID(row["id"]),
            span_id=UUID(row["span_id"]),
            event=row["event"],
            message=row.get("message"),
            timestamp=self._parse_dt(row.get("timestamp")),
            metadata=self._json_loads_dict(row["metadata"]),
        )

    def _row_to_executor(self, row: dict) -> Executor:
        return Executor(
            id=UUID(row["id"]),
            executor_id=row["executor_id"],
            channel_type=row["channel_type"],
            executor_tags=self._json_loads_list(row["executor_tags"]),
            dispatch_type=row["dispatch_type"],
            metadata=self._json_loads_dict(row["metadata"]),
            status=ExecutorStatus(row["status"]),
            current_run_id=self._parse_uuid(row.get("current_run_id")),
            last_heartbeat_at=self._parse_dt(row.get("last_heartbeat_at")),
            registered_at=self._parse_dt(row.get("registered_at")),
        )

    def _row_to_executor_token(self, row: dict) -> ExecutorToken:
        return ExecutorToken(
            id=UUID(row["id"]),
            name=row["name"],
            token_hash=row["token_hash"],
            token_raw=row["token_raw"],
            scope=row["scope"],
            created_at=self._parse_dt(row.get("created_at")),
            revoked_at=self._parse_dt(row.get("revoked_at")),
        )

    def _row_to_wait_condition(self, row: dict) -> WaitCondition:
        return WaitCondition(
            id=UUID(row["id"]),
            run=self._parse_uuid(row.get("run")),
            process=self._parse_uuid(row.get("process")),
            type=WaitConditionType(row["type"]),
            status=WaitConditionStatus(row["status"]),
            pending=self._json_loads_list(row["pending"]),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_trace(self, row: dict) -> Trace:
        return Trace(
            id=UUID(row["id"]),
            run=UUID(row["run"]),
            capability_calls=self._json_loads_list(row["capability_calls"]),
            file_ops=self._json_loads_list(row["file_ops"]),
            model_version=row.get("model_version"),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_alert(self, row: dict) -> Alert:
        return Alert(
            id=UUID(row["id"]),
            severity=row["severity"],
            alert_type=row["alert_type"],
            source=row["source"],
            message=row["message"],
            metadata=self._json_loads_dict(row["metadata"]),
            acknowledged_at=self._parse_dt(row.get("acknowledged_at")),
            resolved_at=self._parse_dt(row.get("resolved_at")),
            created_at=self._parse_dt(row.get("created_at")),
        )

    # ── Epoch ─────────────────────────────────────────────────

    @property
    def reboot_epoch(self) -> int:
        row = self._query_one("SELECT epoch FROM cogos_epoch WHERE id = 1")
        return row["epoch"] if row else 0

    def increment_epoch(self) -> int:
        self._execute("UPDATE cogos_epoch SET epoch = epoch + 1 WHERE id = 1")
        return self.reboot_epoch

    # ── Batch ─────────────────────────────────────────────────

    @contextmanager
    def batch(self) -> Iterator[None]:
        self._batch_depth += 1
        if self._batch_depth == 1:
            self._conn.execute("BEGIN")
        try:
            yield
            if self._batch_depth == 1:
                self._conn.commit()
        except Exception:
            if self._batch_depth == 1:
                self._conn.rollback()
            raise
        finally:
            self._batch_depth -= 1

    # ── Bulk clear ────────────────────────────────────────────

    def clear_all(self) -> None:
        tables = [
            "cogos_span_event", "cogos_span", "cogos_request_trace",
            "cogos_trace", "cogos_delivery", "cogos_handler",
            "cogos_process_capability", "cogos_cron",
            "cogos_channel_message", "cogos_channel",
            "cogos_file_version", "cogos_file",
            "cogos_run", "cogos_process",
            "cogos_capability", "cogos_resource", "cogos_schema",
            "cogos_operation", "cogos_alert", "cogos_meta",
            "cogos_executor_token", "cogos_executor",
            "cogos_discord_channel", "cogos_discord_guild",
            "cogos_wait_condition",
        ]
        for t in tables:
            self._conn.execute(f"DELETE FROM {t}")
        self._conn.execute("UPDATE cogos_epoch SET epoch = 0 WHERE id = 1")
        self._conn.commit()

    def clear_config(self) -> None:
        config_tables = [
            "cogos_span_event", "cogos_span", "cogos_request_trace",
            "cogos_trace", "cogos_delivery", "cogos_channel_message",
            "cogos_run", "cogos_handler", "cogos_process_capability",
            "cogos_cron",
        ]
        for t in config_tables:
            self._conn.execute(f"DELETE FROM {t}")
        self._conn.execute(
            "UPDATE cogos_channel SET owner_process = NULL WHERE owner_process IS NOT NULL"
        )
        config_tables_final = ["cogos_process", "cogos_capability"]
        for t in config_tables_final:
            self._conn.execute(f"DELETE FROM {t}")
        self._conn.commit()

    def delete_files_by_prefixes(self, prefixes: list[str]) -> int:
        total = 0
        for prefix in prefixes:
            total += self._execute(
                "DELETE FROM cogos_file WHERE key LIKE :prefix || '%'",
                {"prefix": prefix},
            )
        return total

    # ── Operations ────────────────────────────────────────────

    def add_operation(self, op: CogosOperation) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_operation (id, epoch, type, metadata, created_at)
               VALUES (:id, :epoch, :type, :metadata, :created_at)""",
            {
                "id": str(op.id),
                "epoch": op.epoch,
                "type": op.type,
                "metadata": self._json_dumps(op.metadata),
                "created_at": op.created_at.isoformat() if op.created_at else now,
            },
        )
        return op.id

    def list_operations(self, limit: int = 50) -> list[CogosOperation]:
        rows = self._query(
            "SELECT * FROM cogos_operation ORDER BY created_at DESC LIMIT :limit",
            {"limit": limit},
        )
        return [self._row_to_operation(r) for r in rows]

    # ── Processes ─────────────────────────────────────────────

    def upsert_process(self, p: Process) -> UUID:
        now = self._now()
        epoch = self.reboot_epoch
        self._execute(
            """INSERT INTO cogos_process
               (id, name, mode, content, priority, resources, required_tags,
                status, runnable_since, parent_process, preemptible, model,
                model_constraints, return_schema, idle_timeout_ms, max_duration_ms,
                max_retries, retry_count, retry_backoff_ms, clear_context,
                metadata, output_events, epoch, tty, executor, schema_id,
                created_at, updated_at)
               VALUES
               (:id, :name, :mode, :content, :priority, :resources, :required_tags,
                :status, :runnable_since, :parent_process, :preemptible, :model,
                :model_constraints, :return_schema, :idle_timeout_ms, :max_duration_ms,
                :max_retries, :retry_count, :retry_backoff_ms, :clear_context,
                :metadata, :output_events, :epoch, :tty, :executor, :schema_id,
                :created_at, :updated_at)
               ON CONFLICT(name, epoch) DO UPDATE SET
                mode=excluded.mode, content=excluded.content, priority=excluded.priority,
                resources=excluded.resources, required_tags=excluded.required_tags,
                status=excluded.status, runnable_since=excluded.runnable_since,
                parent_process=excluded.parent_process, preemptible=excluded.preemptible,
                model=excluded.model, model_constraints=excluded.model_constraints,
                return_schema=excluded.return_schema, idle_timeout_ms=excluded.idle_timeout_ms,
                max_duration_ms=excluded.max_duration_ms, max_retries=excluded.max_retries,
                retry_count=excluded.retry_count, retry_backoff_ms=excluded.retry_backoff_ms,
                clear_context=excluded.clear_context, metadata=excluded.metadata,
                output_events=excluded.output_events, tty=excluded.tty,
                executor=excluded.executor, schema_id=excluded.schema_id,
                updated_at=excluded.updated_at""",
            {
                "id": str(p.id),
                "name": p.name,
                "mode": p.mode.value,
                "content": p.content,
                "priority": p.priority,
                "resources": self._json_dumps(p.resources),
                "required_tags": self._json_dumps(p.required_tags),
                "status": p.status.value,
                "runnable_since": p.runnable_since.isoformat() if p.runnable_since else None,
                "parent_process": str(p.parent_process) if p.parent_process else None,
                "preemptible": int(p.preemptible),
                "model": p.model,
                "model_constraints": self._json_dumps(p.model_constraints),
                "return_schema": self._json_dumps(p.return_schema) if p.return_schema is not None else None,
                "idle_timeout_ms": p.idle_timeout_ms,
                "max_duration_ms": p.max_duration_ms,
                "max_retries": p.max_retries,
                "retry_count": p.retry_count,
                "retry_backoff_ms": p.retry_backoff_ms,
                "clear_context": int(p.clear_context),
                "metadata": self._json_dumps(p.metadata),
                "output_events": self._json_dumps(p.output_events),
                "epoch": p.epoch or epoch,
                "tty": int(p.tty),
                "executor": p.executor,
                "schema_id": str(p.schema_id) if p.schema_id else None,
                "created_at": p.created_at.isoformat() if p.created_at else now,
                "updated_at": now,
            },
        )
        existing = self.get_process_by_name(p.name)
        return existing.id if existing else p.id

    def get_process(self, process_id: UUID) -> Process | None:
        row = self._query_one(
            "SELECT * FROM cogos_process WHERE id = :id", {"id": str(process_id)}
        )
        return self._row_to_process(row) if row else None

    def get_process_by_name(self, name: str) -> Process | None:
        row = self._query_one(
            "SELECT * FROM cogos_process WHERE name = :name AND epoch = :epoch",
            {"name": name, "epoch": self.reboot_epoch},
        )
        return self._row_to_process(row) if row else None

    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]:
        if epoch is None:
            epoch = self.reboot_epoch
        sql = "SELECT * FROM cogos_process WHERE 1=1"
        params: dict[str, Any] = {}
        if status is not None:
            sql += " AND status = :status"
            params["status"] = status.value
        if epoch != ALL_EPOCHS:
            sql += " AND epoch = :epoch"
            params["epoch"] = epoch
        sql += " ORDER BY name LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_process(r) for r in self._query(sql, params)]

    def try_transition_process(
        self, process_id: UUID, from_status: ProcessStatus, to_status: ProcessStatus,
    ) -> bool:
        now = self._now()
        count = self._execute(
            """UPDATE cogos_process SET status = :to_status, updated_at = :now
               WHERE id = :id AND status = :from_status""",
            {
                "to_status": to_status.value,
                "now": now,
                "id": str(process_id),
                "from_status": from_status.value,
            },
        )
        return count > 0

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        now = self._now()
        runnable_since = None
        if status == ProcessStatus.RUNNABLE:
            existing = self.get_process(process_id)
            if existing and existing.runnable_since:
                runnable_since = existing.runnable_since.isoformat()
            else:
                runnable_since = now
        count = self._execute(
            """UPDATE cogos_process SET status = :status, runnable_since = :runnable_since, updated_at = :now
               WHERE id = :id""",
            {
                "status": status.value,
                "runnable_since": runnable_since,
                "now": now,
                "id": str(process_id),
            },
        )
        if count == 0:
            return False
        if status == ProcessStatus.DISABLED:
            self._cascade_disable(process_id)
            self.resolve_wait_conditions_for_process(process_id)
        return True

    def _cascade_disable(self, parent_id: UUID) -> None:
        now = self._now()
        children = self._query(
            "SELECT * FROM cogos_process WHERE parent_process = :pid",
            {"pid": str(parent_id)},
        )
        for row in children:
            if row["status"] != ProcessStatus.DISABLED.value:
                self._execute(
                    """UPDATE cogos_process SET status = :status, runnable_since = NULL, updated_at = :now
                       WHERE id = :id""",
                    {"status": ProcessStatus.DISABLED.value, "now": now, "id": row["id"]},
                )
                self._cascade_disable(UUID(row["id"]))

    def delete_process(self, process_id: UUID) -> bool:
        return self._execute(
            "DELETE FROM cogos_process WHERE id = :id", {"id": str(process_id)}
        ) > 0

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        rows = self._query(
            """SELECT * FROM cogos_process
               WHERE status = 'runnable' AND epoch = :epoch
               ORDER BY priority DESC, runnable_since ASC, name ASC
               LIMIT :limit""",
            {"epoch": self.reboot_epoch, "limit": limit},
        )
        return [self._row_to_process(r) for r in rows]

    def increment_retry(self, process_id: UUID) -> bool:
        return self._execute(
            """UPDATE cogos_process SET retry_count = retry_count + 1, updated_at = :now
               WHERE id = :id""",
            {"now": self._now(), "id": str(process_id)},
        ) > 0

    # ── Wait Conditions ───────────────────────────────────────

    def create_wait_condition(self, wc: WaitCondition) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_wait_condition (id, run, process, type, status, pending, created_at)
               VALUES (:id, :run, :process, :type, :status, :pending, :created_at)""",
            {
                "id": str(wc.id),
                "run": str(wc.run) if wc.run else None,
                "process": str(wc.process) if wc.process else None,
                "type": wc.type.value,
                "status": wc.status.value,
                "pending": self._json_dumps(wc.pending),
                "created_at": wc.created_at.isoformat() if wc.created_at else now,
            },
        )
        return wc.id

    def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None:
        pid = str(process_id)
        row = self._query_one(
            "SELECT * FROM cogos_wait_condition WHERE status = 'pending' AND process = :pid",
            {"pid": pid},
        )
        if row:
            return self._row_to_wait_condition(row)
        rows = self._query(
            """SELECT wc.* FROM cogos_wait_condition wc
               JOIN cogos_run r ON r.id = wc.run
               WHERE wc.status = 'pending' AND r.process = :pid LIMIT 1""",
            {"pid": pid},
        )
        return self._row_to_wait_condition(rows[0]) if rows else None

    def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]:
        row = self._query_one(
            "SELECT pending FROM cogos_wait_condition WHERE id = :id",
            {"id": str(wc_id)},
        )
        if not row:
            return []
        pending = self._json_loads_list(row["pending"])
        pending = [p for p in pending if p != child_pid]
        self._execute(
            "UPDATE cogos_wait_condition SET pending = :pending WHERE id = :id",
            {"pending": self._json_dumps(pending), "id": str(wc_id)},
        )
        return pending

    def resolve_wait_condition(self, wc_id: UUID) -> None:
        self._execute(
            "UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now WHERE id = :id",
            {"now": self._now(), "id": str(wc_id)},
        )

    def resolve_wait_conditions_for_process(self, process_id: UUID) -> None:
        now = self._now()
        self._execute(
            """UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now
               WHERE status = 'pending' AND process = :pid""",
            {"now": now, "pid": str(process_id)},
        )
        run_ids = self._query(
            "SELECT id FROM cogos_run WHERE process = :pid", {"pid": str(process_id)}
        )
        for r in run_ids:
            self._execute(
                """UPDATE cogos_wait_condition SET status = 'resolved', resolved_at = :now
                   WHERE status = 'pending' AND run = :rid""",
                {"now": now, "rid": r["id"]},
            )

    # ── Process Capabilities ──────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        epoch = self.reboot_epoch
        self._execute(
            """INSERT OR REPLACE INTO cogos_process_capability
               (id, process, capability, name, epoch, config)
               VALUES (:id, :process, :capability, :name, :epoch, :config)""",
            {
                "id": str(pc.id),
                "process": str(pc.process),
                "capability": str(pc.capability),
                "name": pc.name,
                "epoch": pc.epoch or epoch,
                "config": self._json_dumps(pc.config),
            },
        )
        return pc.id

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]:
        rows = self._query(
            "SELECT * FROM cogos_process_capability WHERE process = :pid",
            {"pid": str(process_id)},
        )
        return [self._row_to_process_capability(r) for r in rows]

    def delete_process_capability(self, pc_id: UUID) -> bool:
        return self._execute(
            "DELETE FROM cogos_process_capability WHERE id = :id", {"id": str(pc_id)}
        ) > 0

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]:
        rows = self._query(
            """SELECT p.id as process_id, p.name as process_name, p.status as process_status,
                      pc.name as grant_name, pc.config
               FROM cogos_process_capability pc
               JOIN cogos_process p ON p.id = pc.process
               WHERE pc.capability = :cid
               ORDER BY p.name""",
            {"cid": str(capability_id)},
        )
        return [
            {
                "process_id": r["process_id"],
                "process_name": r["process_name"],
                "process_status": r["process_status"],
                "grant_name": r["grant_name"],
                "config": self._json_loads(r["config"]),
            }
            for r in rows
        ]

    # ── Handlers ──────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID:
        now = self._now()
        epoch = self.reboot_epoch
        if h.channel is not None:
            existing = self._query_one(
                "SELECT * FROM cogos_handler WHERE process = :pid AND channel = :cid",
                {"pid": str(h.process), "cid": str(h.channel)},
            )
            if existing:
                self._execute(
                    "UPDATE cogos_handler SET enabled = :enabled WHERE id = :id",
                    {"enabled": int(h.enabled), "id": existing["id"]},
                )
                return UUID(existing["id"])
        self._execute(
            """INSERT INTO cogos_handler (id, process, channel, enabled, epoch, created_at)
               VALUES (:id, :process, :channel, :enabled, :epoch, :created_at)""",
            {
                "id": str(h.id),
                "process": str(h.process),
                "channel": str(h.channel) if h.channel else None,
                "enabled": int(h.enabled),
                "epoch": epoch,
                "created_at": now,
            },
        )
        return h.id

    def list_handlers(
        self,
        *,
        process_id: UUID | None = None,
        enabled_only: bool = False,
        epoch: int | None = None,
        limit: int = 0,
    ) -> list[Handler]:
        sql = "SELECT * FROM cogos_handler WHERE 1=1"
        params: dict[str, Any] = {}
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        if effective_epoch != ALL_EPOCHS:
            sql += " AND epoch = :epoch"
            params["epoch"] = effective_epoch
        if process_id:
            sql += " AND process = :pid"
            params["pid"] = str(process_id)
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY channel"
        if limit > 0:
            sql += f" LIMIT {limit}"
        return [self._row_to_handler(r) for r in self._query(sql, params)]

    def delete_handler(self, handler_id: UUID) -> bool:
        return self._execute(
            "DELETE FROM cogos_handler WHERE id = :id", {"id": str(handler_id)}
        ) > 0

    def match_handlers(self, event_type: str) -> list[Handler]:
        return []

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        rows = self._query(
            "SELECT * FROM cogos_handler WHERE channel = :cid AND enabled = 1",
            {"cid": str(channel_id)},
        )
        return [self._row_to_handler(r) for r in rows]

    # ── Deliveries ────────────────────────────────────────────

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]:
        existing = self._query_one(
            "SELECT id FROM cogos_delivery WHERE message = :mid AND handler = :hid",
            {"mid": str(ed.message), "hid": str(ed.handler)},
        )
        if existing:
            return UUID(existing["id"]), False
        now = self._now()
        epoch = self.reboot_epoch
        self._execute(
            """INSERT INTO cogos_delivery (id, message, handler, trace_id, epoch, status, run, created_at)
               VALUES (:id, :message, :handler, :trace_id, :epoch, :status, :run, :created_at)""",
            {
                "id": str(ed.id),
                "message": str(ed.message),
                "handler": str(ed.handler),
                "trace_id": str(ed.trace_id) if ed.trace_id else None,
                "epoch": epoch,
                "status": ed.status.value,
                "run": str(ed.run) if ed.run else None,
                "created_at": now,
            },
        )
        return ed.id, True

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]:
        rows = self._query(
            """SELECT d.* FROM cogos_delivery d
               JOIN cogos_handler h ON h.id = d.handler
               WHERE d.status = 'pending' AND h.process = :pid
               ORDER BY d.created_at""",
            {"pid": str(process_id)},
        )
        return [self._row_to_delivery(r) for r in rows]

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]:
        sql = "SELECT d.* FROM cogos_delivery d"
        params: dict[str, Any] = {}
        conditions = []
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        if effective_epoch != ALL_EPOCHS:
            conditions.append("d.epoch = :epoch")
            params["epoch"] = effective_epoch
        if message_id is not None:
            conditions.append("d.message = :mid")
            params["mid"] = str(message_id)
        if handler_id is not None:
            conditions.append("d.handler = :hid")
            params["hid"] = str(handler_id)
        if run_id is not None:
            conditions.append("d.run = :rid")
            params["rid"] = str(run_id)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY d.created_at DESC LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_delivery(r) for r in self._query(sql, params)]

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        row = self._query_one(
            """SELECT 1 FROM cogos_delivery d
               JOIN cogos_handler h ON h.id = d.handler
               WHERE d.status = 'pending' AND h.process = :pid LIMIT 1""",
            {"pid": str(process_id)},
        )
        return row is not None

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        return self._execute(
            "UPDATE cogos_delivery SET status = 'delivered', run = :rid WHERE id = :id",
            {"rid": str(run_id), "id": str(delivery_id)},
        ) > 0

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        return self._execute(
            "UPDATE cogos_delivery SET status = 'queued', run = :rid WHERE id = :id",
            {"rid": str(run_id), "id": str(delivery_id)},
        ) > 0

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        return self._execute(
            "UPDATE cogos_delivery SET status = 'pending', run = NULL WHERE id = :id",
            {"id": str(delivery_id)},
        ) > 0

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        return self._execute(
            """UPDATE cogos_delivery SET status = 'delivered'
               WHERE run = :rid AND status IN ('pending', 'queued')""",
            {"rid": str(run_id)},
        )

    def rollback_dispatch(
        self,
        process_id: UUID,
        run_id: UUID,
        delivery_id: UUID | None = None,
        *,
        error: str | None = None,
    ) -> None:
        if delivery_id is not None:
            self.requeue_delivery(delivery_id)
        self.complete_run(run_id, status=RunStatus.FAILED, error=(error or "executor invoke failed")[:4000])
        proc = self.get_process(process_id)
        if proc and proc.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            self.update_process_status(process_id, ProcessStatus.RUNNABLE)

    def get_latest_delivery_time(self, handler_id: UUID) -> datetime | None:
        row = self._query_one(
            """SELECT MAX(cm.created_at) as latest FROM cogos_delivery d
               JOIN cogos_channel_message cm ON cm.id = d.message
               WHERE d.handler = :hid""",
            {"hid": str(handler_id)},
        )
        return self._parse_dt(row["latest"]) if row and row["latest"] else None

    # ── Cron Rules ────────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_cron
               (id, expression, channel_name, payload, enabled, last_run, created_at)
               VALUES (:id, :expression, :channel_name, :payload, :enabled, :last_run, :created_at)""",
            {
                "id": str(c.id),
                "expression": c.expression,
                "channel_name": c.channel_name,
                "payload": self._json_dumps(c.payload),
                "enabled": int(c.enabled),
                "last_run": c.last_run.isoformat() if getattr(c, "last_run", None) else None,
                "created_at": c.created_at.isoformat() if c.created_at else now,
            },
        )
        return c.id

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        sql = "SELECT * FROM cogos_cron"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY expression"
        return [self._row_to_cron(r) for r in self._query(sql)]

    def delete_cron(self, cron_id: UUID) -> bool:
        return self._execute(
            "DELETE FROM cogos_cron WHERE id = :id", {"id": str(cron_id)}
        ) > 0

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        return self._execute(
            "UPDATE cogos_cron SET enabled = :enabled WHERE id = :id",
            {"enabled": int(enabled), "id": str(cron_id)},
        ) > 0

    # ── Files ─────────────────────────────────────────────────

    def insert_file(self, f: File) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_file (id, key, includes, created_at, updated_at)
               VALUES (:id, :key, :includes, :created_at, :updated_at)""",
            {
                "id": str(f.id),
                "key": f.key,
                "includes": self._json_dumps(f.includes),
                "created_at": now,
                "updated_at": now,
            },
        )
        return f.id

    def get_file_by_key(self, key: str) -> File | None:
        row = self._query_one("SELECT * FROM cogos_file WHERE key = :key", {"key": key})
        return self._row_to_file(row) if row else None

    def get_file_by_id(self, file_id: UUID) -> File | None:
        row = self._query_one("SELECT * FROM cogos_file WHERE id = :id", {"id": str(file_id)})
        return self._row_to_file(row) if row else None

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        sql = "SELECT * FROM cogos_file"
        params: dict[str, Any] = {}
        if prefix:
            sql += " WHERE key LIKE :prefix || '%'"
            params["prefix"] = prefix
        sql += " ORDER BY key LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_file(r) for r in self._query(sql, params)]

    def list_files_with_content(
        self,
        *,
        prefix: str | None = None,
        exclude_prefix: str | None = None,
        limit: int = 200,
    ) -> list[tuple[str, str]]:
        sql = """SELECT f.key, fv.content FROM cogos_file f
                 JOIN cogos_file_version fv ON fv.file_id = f.id
                 WHERE fv.is_active = 1"""
        params: dict[str, Any] = {}
        if prefix:
            sql += " AND f.key LIKE :prefix || '%'"
            params["prefix"] = prefix
        if exclude_prefix:
            sql += " AND f.key NOT LIKE :excl || '%'"
            params["excl"] = exclude_prefix
        sql += " ORDER BY f.key LIMIT :limit"
        params["limit"] = limit
        return [(r["key"], r["content"]) for r in self._query(sql, params)]

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100,
    ) -> list[tuple[str, str]]:
        sql = """SELECT f.key, fv.content FROM cogos_file f
                 JOIN cogos_file_version fv ON fv.file_id = f.id
                 WHERE fv.is_active = 1 AND fv.content REGEXP :pattern"""
        params: dict[str, Any] = {"pattern": pattern}
        if prefix:
            sql += " AND f.key LIKE :prefix || '%'"
            params["prefix"] = prefix
        sql += " ORDER BY f.key LIMIT :limit"
        params["limit"] = limit
        rows = self._query(sql, params)
        results = []
        for row in rows:
            assert row["content"] is not None
            results.append((row["key"], row["content"]))
        return results

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200,
    ) -> list[str]:
        import fnmatch
        sql = "SELECT key FROM cogos_file"
        params: dict[str, Any] = {}
        if prefix:
            sql += " WHERE key LIKE :prefix || '%'"
            params["prefix"] = prefix
        sql += " ORDER BY key"
        rows = self._query(sql, params)
        results: list[str] = []
        for row in rows:
            if fnmatch.fnmatch(row["key"], pattern):
                results.append(row["key"])
                if len(results) >= limit:
                    break
        return results

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool:
        return self._execute(
            "UPDATE cogos_file SET includes = :includes, updated_at = :now WHERE id = :id",
            {"includes": self._json_dumps(includes), "now": self._now(), "id": str(file_id)},
        ) > 0

    def delete_file(self, file_id: UUID) -> bool:
        return self._execute(
            "DELETE FROM cogos_file WHERE id = :id", {"id": str(file_id)}
        ) > 0

    def bulk_upsert_files(
        self,
        files: list[tuple[str, str, str, list[str]]],
        *,
        batch_size: int = 100,
    ) -> int:
        with self.batch():
            for key, content, source, includes in files:
                f = self.get_file_by_key(key)
                if f is None:
                    f = File(key=key, includes=includes)
                    self.insert_file(f)
                else:
                    self.update_file_includes(f.id, includes)
                max_v = self.get_max_file_version(f.id)
                self._execute(
                    """UPDATE cogos_file_version SET is_active = 0
                       WHERE file_id = :fid AND is_active = 1""",
                    {"fid": str(f.id)},
                )
                fv = FileVersion(
                    file_id=f.id, version=max_v + 1, content=content,
                    source=source, is_active=True,
                )
                self.insert_file_version(fv)
        return len(files)

    # ── File Versions ─────────────────────────────────────────

    def insert_file_version(self, fv: FileVersion) -> None:
        now = self._now()
        if fv.is_active:
            self._execute(
                "UPDATE cogos_file_version SET is_active = 0 WHERE file_id = :fid AND is_active = 1",
                {"fid": str(fv.file_id)},
            )
        self._execute(
            """INSERT INTO cogos_file_version
               (id, file_id, version, read_only, content, source, is_active, run_id, created_at)
               VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active, :run_id, :created_at)""",
            {
                "id": str(fv.id),
                "file_id": str(fv.file_id),
                "version": fv.version,
                "read_only": int(fv.read_only),
                "content": fv.content,
                "source": fv.source,
                "is_active": int(fv.is_active),
                "run_id": str(fv.run_id) if fv.run_id else None,
                "created_at": now,
            },
        )
        self._execute(
            "UPDATE cogos_file SET updated_at = :now WHERE id = :fid",
            {"now": now, "fid": str(fv.file_id)},
        )

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None:
        row = self._query_one(
            """SELECT * FROM cogos_file_version
               WHERE file_id = :fid AND is_active = 1
               ORDER BY version DESC LIMIT 1""",
            {"fid": str(file_id)},
        )
        return self._row_to_file_version(row) if row else None

    def get_max_file_version(self, file_id: UUID) -> int:
        row = self._query_one(
            "SELECT MAX(version) as max_v FROM cogos_file_version WHERE file_id = :fid",
            {"fid": str(file_id)},
        )
        return row["max_v"] if row and row["max_v"] is not None else 0

    def list_file_versions(self, file_id: UUID, *, limit: int | None = None) -> list[FileVersion]:
        if limit is not None:
            sql = "SELECT * FROM cogos_file_version WHERE file_id = :fid ORDER BY version DESC LIMIT :lim"
            params: dict[str, Any] = {"fid": str(file_id), "lim": limit}
        else:
            sql = "SELECT * FROM cogos_file_version WHERE file_id = :fid ORDER BY version"
            params = {"fid": str(file_id)}
        rows = self._query(sql, params)
        return [self._row_to_file_version(r) for r in rows]

    def set_active_file_version(self, file_id: UUID, version: int) -> None:
        self._execute(
            "UPDATE cogos_file_version SET is_active = 0 WHERE file_id = :fid",
            {"fid": str(file_id)},
        )
        self._execute(
            "UPDATE cogos_file_version SET is_active = 1 WHERE file_id = :fid AND version = :v",
            {"fid": str(file_id), "v": version},
        )

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        return self._execute(
            "UPDATE cogos_file_version SET content = :content WHERE file_id = :fid AND version = :v",
            {"content": content, "fid": str(file_id), "v": version},
        ) > 0

    def delete_file_version(self, file_id: UUID, version: int) -> bool:
        return self._execute(
            "DELETE FROM cogos_file_version WHERE file_id = :fid AND version = :v",
            {"fid": str(file_id), "v": version},
        ) > 0

    # ── Capabilities ──────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_capability
               (id, name, description, instructions, handler, schema,
                iam_role_arn, enabled, metadata, event_types, created_at, updated_at)
               VALUES (:id, :name, :description, :instructions, :handler, :schema,
                :iam_role_arn, :enabled, :metadata, :event_types, :created_at, :updated_at)""",
            {
                "id": str(cap.id),
                "name": cap.name,
                "description": cap.description,
                "instructions": cap.instructions,
                "handler": cap.handler,
                "schema": self._json_dumps(cap.schema),
                "iam_role_arn": cap.iam_role_arn,
                "enabled": int(cap.enabled),
                "metadata": self._json_dumps(cap.metadata),
                "event_types": self._json_dumps(getattr(cap, "event_types", [])),
                "created_at": cap.created_at.isoformat() if cap.created_at else now,
                "updated_at": now,
            },
        )
        return cap.id

    def get_capability(self, cap_id: UUID) -> Capability | None:
        row = self._query_one("SELECT * FROM cogos_capability WHERE id = :id", {"id": str(cap_id)})
        return self._row_to_capability(row) if row else None

    def get_capability_by_name(self, name: str) -> Capability | None:
        row = self._query_one("SELECT * FROM cogos_capability WHERE name = :name", {"name": name})
        return self._row_to_capability(row) if row else None

    def get_capability_by_handler(self, handler: str) -> Capability | None:
        row = self._query_one(
            "SELECT * FROM cogos_capability WHERE handler = :handler", {"handler": handler}
        )
        return self._row_to_capability(row) if row else None

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]:
        sql = "SELECT * FROM cogos_capability"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY name"
        return [self._row_to_capability(r) for r in self._query(sql)]

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]:
        if process_id:
            sql = """SELECT c.* FROM cogos_capability c
                     JOIN cogos_process_capability pc ON pc.capability = c.id
                     WHERE c.enabled = 1 AND pc.process = :pid
                     AND (c.name LIKE '%' || :q || '%' OR c.description LIKE '%' || :q || '%')
                     ORDER BY c.name"""
            rows = self._query(sql, {"pid": str(process_id), "q": query})
        else:
            sql = """SELECT * FROM cogos_capability
                     WHERE enabled = 1
                     AND (name LIKE '%' || :q || '%' OR description LIKE '%' || :q || '%')
                     ORDER BY name"""
            rows = self._query(sql, {"q": query})
        return [self._row_to_capability(r) for r in rows]

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, resource: Resource) -> str:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_resource
               (id, name, resource_type, capacity, metadata, created_at)
               VALUES (:id, :name, :resource_type, :capacity, :metadata, :created_at)""",
            {
                "id": str(resource.id),
                "name": resource.name,
                "resource_type": resource.resource_type.value,
                "capacity": resource.capacity,
                "metadata": self._json_dumps(resource.metadata),
                "created_at": resource.created_at.isoformat() if resource.created_at else now,
            },
        )
        return resource.name

    def list_resources(self) -> list[Resource]:
        return [self._row_to_resource(r) for r in self._query("SELECT * FROM cogos_resource ORDER BY name")]

    # ── Runs ──────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        now = self._now()
        epoch = self.reboot_epoch
        self._execute(
            """INSERT INTO cogos_run
               (id, process, message, conversation, status, tokens_in, tokens_out,
                cost_usd, duration_ms, error, model_version, result, snapshot,
                scope_log, epoch, trace_id, parent_trace_id, metadata, created_at, completed_at)
               VALUES
               (:id, :process, :message, :conversation, :status, :tokens_in, :tokens_out,
                :cost_usd, :duration_ms, :error, :model_version, :result, :snapshot,
                :scope_log, :epoch, :trace_id, :parent_trace_id, :metadata, :created_at, :completed_at)""",
            {
                "id": str(run.id),
                "process": str(run.process),
                "message": str(run.message) if run.message else None,
                "conversation": str(run.conversation) if run.conversation else None,
                "status": run.status.value,
                "tokens_in": run.tokens_in,
                "tokens_out": run.tokens_out,
                "cost_usd": str(run.cost_usd),
                "duration_ms": run.duration_ms,
                "error": run.error,
                "model_version": run.model_version,
                "result": self._json_dumps(run.result) if run.result is not None else None,
                "snapshot": self._json_dumps(run.snapshot) if run.snapshot is not None else None,
                "scope_log": self._json_dumps(run.scope_log),
                "epoch": epoch,
                "trace_id": str(run.trace_id) if run.trace_id else None,
                "parent_trace_id": str(run.parent_trace_id) if run.parent_trace_id else None,
                "metadata": self._json_dumps(run.metadata) if run.metadata is not None else None,
                "created_at": run.created_at.isoformat() if run.created_at else now,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            },
        )
        return run.id

    def complete_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: Decimal = Decimal("0"),
        duration_ms: int | None = None,
        error: str | None = None,
        model_version: str | None = None,
        result: dict | None = None,
        snapshot: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool:
        now = self._now()
        sets = [
            "status = :status", "tokens_in = :tokens_in", "tokens_out = :tokens_out",
            "cost_usd = :cost_usd", "duration_ms = :duration_ms", "error = :error",
            "completed_at = :completed_at",
        ]
        params: dict[str, Any] = {
            "status": status.value,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost_usd),
            "duration_ms": duration_ms,
            "error": error,
            "completed_at": now,
            "id": str(run_id),
        }
        if model_version is not None:
            sets.append("model_version = :model_version")
            params["model_version"] = model_version
        if result is not None:
            sets.append("result = :result")
            params["result"] = self._json_dumps(result)
        if snapshot is not None:
            sets.append("snapshot = :snapshot")
            params["snapshot"] = self._json_dumps(snapshot)
        if scope_log is not None:
            sets.append("scope_log = :scope_log")
            params["scope_log"] = self._json_dumps(scope_log)
        sql = f"UPDATE cogos_run SET {', '.join(sets)} WHERE id = :id"
        return self._execute(sql, params) > 0

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int:
        from datetime import timedelta
        threshold = (datetime.now(UTC) - timedelta(milliseconds=max_age_ms)).isoformat()
        now = self._now()
        return self._execute(
            """UPDATE cogos_run SET status = 'timeout',
               error = 'Run exceeded maximum duration and was reaped by dispatcher',
               completed_at = :now
               WHERE status = 'running' AND created_at < :threshold""",
            {"now": now, "threshold": threshold},
        )

    def get_run(self, run_id: UUID) -> Run | None:
        row = self._query_one("SELECT * FROM cogos_run WHERE id = :id", {"id": str(run_id)})
        return self._row_to_run(row) if row else None

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(milliseconds=max_age_ms)).isoformat()
        epoch = self.reboot_epoch
        rows = self._query(
            """SELECT * FROM cogos_run
               WHERE epoch = :epoch
               AND status IN ('failed', 'timeout', 'throttled')
               AND (completed_at >= :cutoff OR created_at >= :cutoff)""",
            {"epoch": epoch, "cutoff": cutoff},
        )
        return [self._row_to_run(r) for r in rows]

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None:
        row = self._query_one("SELECT metadata FROM cogos_run WHERE id = :id", {"id": str(run_id)})
        if row is None:
            return
        current = self._json_loads_dict(row["metadata"])
        current.update(metadata)
        self._execute(
            "UPDATE cogos_run SET metadata = :metadata WHERE id = :id",
            {"metadata": self._json_dumps(current), "id": str(run_id)},
        )

    def list_runs(
        self,
        *,
        process_id: UUID | None = None,
        process_ids: list[UUID] | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
        epoch: int | None = None,
        slim: bool = False,
    ) -> list[Run]:
        if slim:
            cols = ("id, process, message, conversation, status, tokens_in, tokens_out, "
                    "cost_usd, duration_ms, error, model_version, epoch, trace_id, "
                    "parent_trace_id, metadata, created_at, completed_at, "
                    "NULL as result, NULL as snapshot, '[]' as scope_log")
        else:
            cols = "*"
        sql = f"SELECT {cols} FROM cogos_run"
        params: dict[str, Any] = {}
        conditions = []
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params["epoch"] = effective_epoch
        if process_id is not None:
            conditions.append("process = :pid")
            params["pid"] = str(process_id)
        if process_ids:
            placeholders = ", ".join(f":pid_{i}" for i in range(len(process_ids)))
            conditions.append(f"process IN ({placeholders})")
            for i, pid in enumerate(process_ids):
                params[f"pid_{i}"] = str(pid)
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if since:
            conditions.append("created_at >= :since")
            params["since"] = since.replace("Z", "+00:00")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_run(r) for r in self._query(sql, params)]

    def list_file_mutations(self, run_id: UUID) -> list[dict]:
        rows = self._query(
            """SELECT f.key, fv.file_id, fv.version, fv.content, fv.created_at
               FROM cogos_file_version fv
               JOIN cogos_file f ON f.id = fv.file_id
               WHERE fv.run_id = :rid
               ORDER BY fv.created_at""",
            {"rid": str(run_id)},
        )
        return [
            {
                "key": r["key"],
                "file_id": r["file_id"],
                "version": r["version"],
                "content": r["content"],
                "created_at": self._parse_dt(r["created_at"]),
            }
            for r in rows
        ]

    def get_file_version_content(self, file_id: UUID, version: int) -> str | None:
        row = self._query_one(
            "SELECT content FROM cogos_file_version WHERE file_id = :fid AND version = :v",
            {"fid": str(file_id), "v": version},
        )
        return row["content"] if row else None

    def list_messages_sent_by_run(self, run_id: UUID) -> list[dict]:
        rows = self._query(
            """SELECT cm.id, cm.payload, cm.created_at, c.name AS channel_name
               FROM cogos_channel_message cm
               JOIN cogos_channel c ON c.id = cm.channel
               WHERE cm.sender_run_id = :rid
               ORDER BY cm.created_at""",
            {"rid": str(run_id)},
        )
        return [
            {
                "id": r["id"],
                "channel_name": r["channel_name"],
                "payload": self._json_loads_dict(r["payload"]),
                "created_at": self._parse_dt(r["created_at"]),
            }
            for r in rows
        ]

    def list_child_runs(self, process_id: UUID) -> list[Run]:
        rows = self._query(
            """SELECT r.* FROM cogos_run r
               JOIN cogos_process p ON p.id = r.process
               WHERE p.parent_process = :pid
               ORDER BY r.created_at""",
            {"pid": str(process_id)},
        )
        return [self._row_to_run(r) for r in rows]

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        sql = """SELECT r.* FROM cogos_run r
                 JOIN cogos_process p ON p.id = r.process
                 WHERE p.name GLOB :pattern"""
        params: dict[str, Any] = {"pattern": name_pattern}
        if status:
            sql += " AND r.status = :status"
            params["status"] = status
        if since:
            sql += " AND r.created_at >= :since"
            params["since"] = since.replace("Z", "+00:00")
        sql += " ORDER BY r.created_at DESC LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_run(r) for r in self._query(sql, params)]

    # ── Traces ────────────────────────────────────────────────

    def create_trace(self, trace: Trace) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_trace (id, run, capability_calls, file_ops, model_version, created_at)
               VALUES (:id, :run, :capability_calls, :file_ops, :model_version, :created_at)""",
            {
                "id": str(trace.id),
                "run": str(trace.run),
                "capability_calls": self._json_dumps(trace.capability_calls),
                "file_ops": self._json_dumps(trace.file_ops),
                "model_version": trace.model_version,
                "created_at": trace.created_at.isoformat() if trace.created_at else now,
            },
        )
        return trace.id

    # ── Request Traces & Spans ────────────────────────────────

    def create_request_trace(self, trace: RequestTrace) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_request_trace (id, cogent_id, source, source_ref, created_at)
               VALUES (:id, :cogent_id, :source, :source_ref, :created_at)""",
            {
                "id": str(trace.id),
                "cogent_id": trace.cogent_id,
                "source": trace.source,
                "source_ref": trace.source_ref,
                "created_at": now,
            },
        )
        return trace.id

    def get_request_trace(self, trace_id: UUID) -> RequestTrace | None:
        row = self._query_one(
            "SELECT * FROM cogos_request_trace WHERE id = :id", {"id": str(trace_id)}
        )
        return self._row_to_request_trace(row) if row else None

    def create_span(self, span: Span) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_span
               (id, trace_id, parent_span_id, name, coglet, status, metadata, started_at, ended_at)
               VALUES (:id, :trace_id, :parent_span_id, :name, :coglet, :status, :metadata, :started_at, :ended_at)""",
            {
                "id": str(span.id),
                "trace_id": str(span.trace_id),
                "parent_span_id": str(span.parent_span_id) if span.parent_span_id else None,
                "name": span.name,
                "coglet": span.coglet,
                "status": span.status.value,
                "metadata": self._json_dumps(span.metadata),
                "started_at": now,
                "ended_at": None,
            },
        )
        return span.id

    def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool:
        now = self._now()
        if metadata:
            row = self._query_one("SELECT metadata FROM cogos_span WHERE id = :id", {"id": str(span_id)})
            if row:
                current = self._json_loads_dict(row["metadata"])
                current.update(metadata)
                return self._execute(
                    "UPDATE cogos_span SET status = :status, metadata = :metadata, ended_at = :now WHERE id = :id",
                    {"status": status, "metadata": self._json_dumps(current), "now": now, "id": str(span_id)},
                ) > 0
            return False
        return self._execute(
            "UPDATE cogos_span SET status = :status, ended_at = :now WHERE id = :id",
            {"status": status, "now": now, "id": str(span_id)},
        ) > 0

    def list_spans(self, trace_id: UUID) -> list[Span]:
        rows = self._query(
            "SELECT * FROM cogos_span WHERE trace_id = :tid ORDER BY started_at",
            {"tid": str(trace_id)},
        )
        return [self._row_to_span(r) for r in rows]

    def create_span_event(self, event: SpanEvent) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_span_event (id, span_id, event, message, metadata, timestamp)
               VALUES (:id, :span_id, :event, :message, :metadata, :timestamp)""",
            {
                "id": str(event.id),
                "span_id": str(event.span_id),
                "event": event.event,
                "message": event.message,
                "metadata": self._json_dumps(event.metadata),
                "timestamp": now,
            },
        )
        return event.id

    def list_span_events(self, span_id: UUID) -> list[SpanEvent]:
        rows = self._query(
            "SELECT * FROM cogos_span_event WHERE span_id = :sid ORDER BY timestamp",
            {"sid": str(span_id)},
        )
        return [self._row_to_span_event(r) for r in rows]

    def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]:
        rows = self._query(
            """SELECT se.* FROM cogos_span_event se
               JOIN cogos_span s ON s.id = se.span_id
               WHERE s.trace_id = :tid ORDER BY se.timestamp""",
            {"tid": str(trace_id)},
        )
        return [self._row_to_span_event(r) for r in rows]

    # ── Meta ──────────────────────────────────────────────────

    def set_meta(self, key: str, value: str = "") -> None:
        self._execute(
            "INSERT OR REPLACE INTO cogos_meta (key, value) VALUES (:key, :value)",
            {"key": key, "value": value},
        )

    def get_meta(self, key: str) -> dict[str, str] | None:
        row = self._query_one("SELECT * FROM cogos_meta WHERE key = :key", {"key": key})
        if row is None:
            return None
        return {"key": row["key"], "value": row["value"]}

    # ── Alerts ────────────────────────────────────────────────

    def create_alert(
        self,
        severity: str,
        alert_type: str,
        source: str,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_alert (id, severity, alert_type, source, message, metadata, created_at)
               VALUES (:id, :severity, :alert_type, :source, :message, :metadata, :created_at)""",
            {
                "id": str(uuid4()),
                "severity": severity,
                "alert_type": alert_type,
                "source": source,
                "message": message,
                "metadata": self._json_dumps(metadata or {}),
                "created_at": now,
            },
        )

    def list_alerts(self, *, resolved: bool = False, limit: int = 50) -> list:
        if resolved:
            rows = self._query(
                "SELECT * FROM cogos_alert ORDER BY created_at DESC LIMIT :limit",
                {"limit": limit},
            )
        else:
            rows = self._query(
                "SELECT * FROM cogos_alert WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT :limit",
                {"limit": limit},
            )
        return [self._row_to_alert(r) for r in rows]

    def resolve_alert(self, alert_id: UUID) -> None:
        self._execute(
            "UPDATE cogos_alert SET resolved_at = :now WHERE id = :id",
            {"now": self._now(), "id": str(alert_id)},
        )

    def resolve_all_alerts(self) -> int:
        return self._execute(
            "UPDATE cogos_alert SET resolved_at = :now WHERE resolved_at IS NULL",
            {"now": self._now()},
        )

    def delete_alert(self, alert_id: UUID) -> None:
        self._execute("DELETE FROM cogos_alert WHERE id = :id", {"id": str(alert_id)})

    # ── Schemas ───────────────────────────────────────────────

    def upsert_schema(self, s: Schema) -> UUID:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_schema (id, name, definition, file_id, created_at)
               VALUES (:id, :name, :definition, :file_id, :created_at)""",
            {
                "id": str(s.id),
                "name": s.name,
                "definition": self._json_dumps(s.definition),
                "file_id": str(s.file_id) if s.file_id else None,
                "created_at": s.created_at.isoformat() if s.created_at else now,
            },
        )
        return s.id

    def get_schema(self, schema_id: UUID) -> Schema | None:
        row = self._query_one("SELECT * FROM cogos_schema WHERE id = :id", {"id": str(schema_id)})
        return self._row_to_schema(row) if row else None

    def get_schema_by_name(self, name: str) -> Schema | None:
        row = self._query_one("SELECT * FROM cogos_schema WHERE name = :name", {"name": name})
        return self._row_to_schema(row) if row else None

    def list_schemas(self) -> list[Schema]:
        return [self._row_to_schema(r) for r in self._query("SELECT * FROM cogos_schema ORDER BY name")]

    # ── Channels ──────────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> UUID:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_channel
               (id, name, channel_type, owner_process, schema_id,
                inline_schema, auto_close, closed_at, created_at)
               VALUES (:id, :name, :channel_type, :owner_process, :schema_id,
                :inline_schema, :auto_close, :closed_at, :created_at)""",
            {
                "id": str(ch.id),
                "name": ch.name,
                "channel_type": ch.channel_type.value,
                "owner_process": str(ch.owner_process) if ch.owner_process else None,
                "schema_id": str(ch.schema_id) if ch.schema_id else None,
                "inline_schema": self._json_dumps(ch.inline_schema) if ch.inline_schema else None,
                "auto_close": int(ch.auto_close),
                "closed_at": ch.closed_at.isoformat() if ch.closed_at else None,
                "created_at": ch.created_at.isoformat() if ch.created_at else now,
            },
        )
        return ch.id

    def get_channel(self, channel_id: UUID) -> Channel | None:
        row = self._query_one("SELECT * FROM cogos_channel WHERE id = :id", {"id": str(channel_id)})
        return self._row_to_channel(row) if row else None

    def get_channel_by_name(self, name: str) -> Channel | None:
        row = self._query_one("SELECT * FROM cogos_channel WHERE name = :name", {"name": name})
        return self._row_to_channel(row) if row else None

    def list_channels(self, *, owner_process: UUID | None = None, limit: int = 0) -> list[Channel]:
        sql = "SELECT * FROM cogos_channel"
        params: dict[str, Any] = {}
        if owner_process is not None:
            sql += " WHERE owner_process = :op"
            params["op"] = str(owner_process)
        sql += " ORDER BY name"
        if limit > 0:
            sql += " LIMIT :limit"
            params["limit"] = limit
        return [self._row_to_channel(r) for r in self._query(sql, params)]

    def close_channel(self, channel_id: UUID) -> bool:
        return self._execute(
            "UPDATE cogos_channel SET closed_at = :now WHERE id = :id",
            {"now": self._now(), "id": str(channel_id)},
        ) > 0

    # ── Channel Messages ──────────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        if msg.created_at is None:
            msg.created_at = datetime.now(UTC)

        if msg.idempotency_key:
            existing = self._query_one(
                """SELECT id FROM cogos_channel_message
                   WHERE channel = :cid AND idempotency_key = :key""",
                {"cid": str(msg.channel), "key": msg.idempotency_key},
            )
            if existing:
                return UUID(existing["id"])

        self._execute(
            """INSERT INTO cogos_channel_message
               (id, channel, sender_process, sender_run_id, payload,
                idempotency_key, trace_id, trace_meta, created_at)
               VALUES (:id, :channel, :sender_process, :sender_run_id, :payload,
                :idempotency_key, :trace_id, :trace_meta, :created_at)""",
            {
                "id": str(msg.id),
                "channel": str(msg.channel),
                "sender_process": str(msg.sender_process) if msg.sender_process else None,
                "sender_run_id": str(msg.sender_run_id) if msg.sender_run_id else None,
                "payload": self._json_dumps(msg.payload),
                "idempotency_key": msg.idempotency_key,
                "trace_id": str(msg.trace_id) if msg.trace_id else None,
                "trace_meta": self._json_dumps(msg.trace_meta) if msg.trace_meta else None,
                "created_at": msg.created_at.isoformat(),
            },
        )

        handlers = self.match_handlers_by_channel(msg.channel)
        for handler in handlers:
            delivery = Delivery(message=msg.id, handler=handler.id, trace_id=msg.trace_id)
            _delivery_id, inserted = self.create_delivery(delivery)
            if inserted:
                proc = self.get_process(handler.process)
                if proc and proc.status == ProcessStatus.WAITING:
                    wc = self.get_pending_wait_condition_for_process(handler.process)
                    if wc is None:
                        self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                        self._nudge_ingress(process_id=handler.process)
                    else:
                        payload = msg.payload if isinstance(msg.payload, dict) else {}
                        if payload.get("type") == "child:exited":
                            sender_pid = str(msg.sender_process)
                            remaining = self.remove_from_pending(wc.id, sender_pid)
                            should_wake = (
                                wc.type.value in ("wait", "wait_any")
                                or (wc.type.value == "wait_all" and len(remaining) == 0)
                            )
                            if should_wake:
                                self.resolve_wait_condition(wc.id)
                                self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                                self._nudge_ingress(process_id=handler.process)

        return msg.id

    def get_channel_message(self, message_id: UUID) -> ChannelMessage | None:
        row = self._query_one(
            "SELECT * FROM cogos_channel_message WHERE id = :id", {"id": str(message_id)}
        )
        return self._row_to_channel_message(row) if row else None

    def list_channel_messages(
        self, channel_id: UUID | None = None, *, limit: int = 100, since: datetime | None = None,
    ) -> list[ChannelMessage]:
        sql = "SELECT * FROM cogos_channel_message"
        params: dict[str, Any] = {}
        conditions = []
        if channel_id is not None:
            conditions.append("channel = :cid")
            params["cid"] = str(channel_id)
        if since is not None:
            conditions.append("created_at > :since")
            params["since"] = since.isoformat()
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if channel_id is not None:
            sql += " ORDER BY created_at ASC"
        else:
            sql += " ORDER BY created_at DESC"
        sql += " LIMIT :limit"
        params["limit"] = limit
        return [self._row_to_channel_message(r) for r in self._query(sql, params)]

    # ── Discord Metadata ──────────────────────────────────────

    def upsert_discord_guild(self, guild: DiscordGuild) -> None:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_discord_guild
               (guild_id, cogent_name, name, icon_url, member_count, synced_at)
               VALUES (:guild_id, :cogent_name, :name, :icon_url, :member_count, :synced_at)""",
            {
                "guild_id": guild.guild_id,
                "cogent_name": guild.cogent_name,
                "name": guild.name,
                "icon_url": guild.icon_url,
                "member_count": guild.member_count,
                "synced_at": now,
            },
        )

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
        row = self._query_one(
            "SELECT * FROM cogos_discord_guild WHERE guild_id = :gid", {"gid": guild_id}
        )
        return self._row_to_discord_guild(row) if row else None

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
        if cogent_name:
            rows = self._query(
                "SELECT * FROM cogos_discord_guild WHERE cogent_name = :cn",
                {"cn": cogent_name},
            )
        else:
            rows = self._query("SELECT * FROM cogos_discord_guild")
        return [self._row_to_discord_guild(r) for r in rows]

    def delete_discord_guild(self, guild_id: str) -> None:
        self._execute(
            "DELETE FROM cogos_discord_channel WHERE guild_id = :gid", {"gid": guild_id}
        )
        self._execute(
            "DELETE FROM cogos_discord_guild WHERE guild_id = :gid", {"gid": guild_id}
        )

    def upsert_discord_channel(self, channel: DiscordChannel) -> None:
        now = self._now()
        self._execute(
            """INSERT OR REPLACE INTO cogos_discord_channel
               (channel_id, guild_id, name, topic, category, channel_type, position, synced_at)
               VALUES (:channel_id, :guild_id, :name, :topic, :category, :channel_type, :position, :synced_at)""",
            {
                "channel_id": channel.channel_id,
                "guild_id": channel.guild_id,
                "name": channel.name,
                "topic": channel.topic,
                "category": channel.category,
                "channel_type": channel.channel_type,
                "position": channel.position,
                "synced_at": now,
            },
        )

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
        row = self._query_one(
            "SELECT * FROM cogos_discord_channel WHERE channel_id = :cid", {"cid": channel_id}
        )
        return self._row_to_discord_channel(row) if row else None

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
        if guild_id:
            rows = self._query(
                "SELECT * FROM cogos_discord_channel WHERE guild_id = :gid ORDER BY position",
                {"gid": guild_id},
            )
        else:
            rows = self._query("SELECT * FROM cogos_discord_channel ORDER BY position")
        return [self._row_to_discord_channel(r) for r in rows]

    def delete_discord_channel(self, channel_id: str) -> None:
        self._execute(
            "DELETE FROM cogos_discord_channel WHERE channel_id = :cid", {"cid": channel_id}
        )

    # ── Executors ─────────────────────────────────────────────

    def register_executor(self, executor: Executor) -> UUID:
        now = self._now()
        existing = self._query_one(
            "SELECT id FROM cogos_executor WHERE executor_id = :eid",
            {"eid": executor.executor_id},
        )
        if existing:
            executor.id = UUID(existing["id"])
        self._execute(
            """INSERT OR REPLACE INTO cogos_executor
               (id, executor_id, channel_type, executor_tags, status, current_run_id,
                dispatch_type, metadata, last_heartbeat_at, registered_at)
               VALUES (:id, :executor_id, :channel_type, :executor_tags, :status, :current_run_id,
                :dispatch_type, :metadata, :last_heartbeat_at, :registered_at)""",
            {
                "id": str(executor.id),
                "executor_id": executor.executor_id,
                "channel_type": executor.channel_type,
                "executor_tags": self._json_dumps(executor.executor_tags),
                "status": ExecutorStatus.IDLE.value,
                "current_run_id": None,
                "dispatch_type": executor.dispatch_type,
                "metadata": self._json_dumps(executor.metadata),
                "last_heartbeat_at": now,
                "registered_at": now,
            },
        )
        return executor.id

    def get_executor(self, executor_id: str) -> Executor | None:
        row = self._query_one(
            "SELECT * FROM cogos_executor WHERE executor_id = :eid", {"eid": executor_id}
        )
        return self._row_to_executor(row) if row else None

    def get_executor_by_id(self, id: UUID) -> Executor | None:
        row = self._query_one(
            "SELECT * FROM cogos_executor WHERE id = :id", {"id": str(id)}
        )
        return self._row_to_executor(row) if row else None

    def list_executors(self, status: ExecutorStatus | None = None) -> list[Executor]:
        if status:
            rows = self._query(
                "SELECT * FROM cogos_executor WHERE status = :status ORDER BY registered_at DESC",
                {"status": status.value},
            )
        else:
            rows = self._query("SELECT * FROM cogos_executor ORDER BY registered_at DESC")
        return [self._row_to_executor(r) for r in rows]

    def select_executor(
        self,
        required_tags: list[str] | None = None,
        preferred_tags: list[str] | None = None,
    ) -> Executor | None:
        idle = self.list_executors(status=ExecutorStatus.IDLE)
        if not idle:
            return None
        candidates = idle
        if required_tags:
            req = set(required_tags)
            candidates = [e for e in candidates if req.issubset(set(e.executor_tags))]
        if not candidates:
            return None
        if preferred_tags:
            pref = set(preferred_tags)
            candidates.sort(key=lambda e: len(pref & set(e.executor_tags)), reverse=True)
        return candidates[0]

    def heartbeat_executor(
        self,
        executor_id: str,
        status: ExecutorStatus = ExecutorStatus.IDLE,
        current_run_id: UUID | None = None,
        resource_usage: dict | None = None,
    ) -> bool:
        now = self._now()
        if resource_usage:
            row = self._query_one(
                "SELECT metadata FROM cogos_executor WHERE executor_id = :eid",
                {"eid": executor_id},
            )
            if row:
                meta = self._json_loads_dict(row["metadata"])
                meta["resource_usage"] = resource_usage
                return self._execute(
                    """UPDATE cogos_executor SET last_heartbeat_at = :now, status = :status,
                       current_run_id = :rid, metadata = :metadata WHERE executor_id = :eid""",
                    {
                        "now": now, "status": status.value,
                        "rid": str(current_run_id) if current_run_id else None,
                        "metadata": self._json_dumps(meta), "eid": executor_id,
                    },
                ) > 0
        return self._execute(
            """UPDATE cogos_executor SET last_heartbeat_at = :now, status = :status,
               current_run_id = :rid WHERE executor_id = :eid""",
            {
                "now": now, "status": status.value,
                "rid": str(current_run_id) if current_run_id else None,
                "eid": executor_id,
            },
        ) > 0

    def update_executor_status(
        self, executor_id: str, status: ExecutorStatus, current_run_id: UUID | None = None,
    ) -> None:
        self._execute(
            "UPDATE cogos_executor SET status = :status, current_run_id = :rid WHERE executor_id = :eid",
            {
                "status": status.value,
                "rid": str(current_run_id) if current_run_id else None,
                "eid": executor_id,
            },
        )

    def delete_executor(self, executor_id: str) -> None:
        self._execute(
            "DELETE FROM cogos_executor WHERE executor_id = :eid", {"eid": executor_id}
        )

    def reap_stale_executors(self, heartbeat_interval_s: int = 30) -> int:
        from datetime import timedelta
        now = datetime.now(UTC)
        dead_threshold = (now - timedelta(seconds=heartbeat_interval_s * 10)).isoformat()
        stale_threshold = (now - timedelta(seconds=heartbeat_interval_s * 3)).isoformat()
        dead_count = self._execute(
            """UPDATE cogos_executor SET status = 'dead'
               WHERE status != 'dead' AND last_heartbeat_at IS NOT NULL
               AND last_heartbeat_at < :threshold""",
            {"threshold": dead_threshold},
        )
        self._execute(
            """UPDATE cogos_executor SET status = 'stale'
               WHERE status = 'idle' AND last_heartbeat_at IS NOT NULL
               AND last_heartbeat_at < :threshold AND last_heartbeat_at >= :dead""",
            {"threshold": stale_threshold, "dead": dead_threshold},
        )
        return dead_count

    # ── Executor Tokens ───────────────────────────────────────

    def create_executor_token(self, token: ExecutorToken) -> UUID:
        now = self._now()
        self._execute(
            """INSERT INTO cogos_executor_token
               (id, name, token_hash, token_raw, scope, created_at, revoked_at)
               VALUES (:id, :name, :token_hash, :token_raw, :scope, :created_at, :revoked_at)""",
            {
                "id": str(token.id),
                "name": token.name,
                "token_hash": token.token_hash,
                "token_raw": token.token_raw,
                "scope": token.scope,
                "created_at": now,
                "revoked_at": None,
            },
        )
        return token.id

    def get_executor_token_by_hash(self, token_hash: str) -> ExecutorToken | None:
        row = self._query_one(
            "SELECT * FROM cogos_executor_token WHERE token_hash = :hash AND revoked_at IS NULL",
            {"hash": token_hash},
        )
        return self._row_to_executor_token(row) if row else None

    def list_executor_tokens(self) -> list[ExecutorToken]:
        rows = self._query("SELECT * FROM cogos_executor_token ORDER BY created_at DESC")
        return [self._row_to_executor_token(r) for r in rows]

    def revoke_executor_token(self, name: str) -> bool:
        return self._execute(
            "UPDATE cogos_executor_token SET revoked_at = :now WHERE name = :name AND revoked_at IS NULL",
            {"now": self._now(), "name": name},
        ) > 0

    # ── Lifecycle ─────────────────────────────────────────────

    def reload(self) -> None:
        pass

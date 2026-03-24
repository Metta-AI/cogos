from __future__ import annotations

import json
import logging
import os
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
from cogos.db.models.alert import Alert, AlertSeverity
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
    config      TEXT,
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
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.create_function("regexp", 2, lambda pattern, string: bool(re.search(pattern, string or "")))
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
        return [dict(zip(cols, row)) for row in cur.fetchall()]

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
            resources=self._json_loads(row["resources"]) or [],
            required_tags=self._json_loads(row["required_tags"]) or [],
            executor=row["executor"],
            status=ProcessStatus(row["status"]),
            runnable_since=self._parse_dt(row.get("runnable_since")),
            parent_process=self._parse_uuid(row.get("parent_process")),
            preemptible=bool(row["preemptible"]),
            model=row.get("model"),
            model_constraints=self._json_loads(row["model_constraints"]) or {},
            return_schema=self._json_loads(row.get("return_schema")),
            idle_timeout_ms=row.get("idle_timeout_ms"),
            max_duration_ms=row.get("max_duration_ms"),
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            retry_backoff_ms=row.get("retry_backoff_ms"),
            clear_context=bool(row["clear_context"]),
            tty=bool(row["tty"]),
            metadata=self._json_loads(row["metadata"]) or {},
            output_events=self._json_loads(row["output_events"]) or [],
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
            schema=self._json_loads(row["schema"]) or {},
            iam_role_arn=row.get("iam_role_arn"),
            enabled=bool(row["enabled"]),
            metadata=self._json_loads(row["metadata"]) or {},
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
            includes=self._json_loads(row["includes"]) or [],
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
            metadata=self._json_loads(row["metadata"]) or {},
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_cron(self, row: dict) -> Cron:
        return Cron(
            id=UUID(row["id"]),
            expression=row["expression"],
            channel_name=row["channel_name"],
            payload=self._json_loads(row["payload"]) or {},
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
            scope_log=self._json_loads(row["scope_log"]) or [],
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
            definition=self._json_loads(row["definition"]) or {},
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
            payload=self._json_loads(row["payload"]) or {},
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
            metadata=self._json_loads(row["metadata"]) or {},
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
            metadata=self._json_loads(row["metadata"]) or {},
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
            metadata=self._json_loads(row["metadata"]) or {},
        )

    def _row_to_executor(self, row: dict) -> Executor:
        return Executor(
            id=UUID(row["id"]),
            executor_id=row["executor_id"],
            channel_type=row["channel_type"],
            executor_tags=self._json_loads(row["executor_tags"]) or [],
            dispatch_type=row["dispatch_type"],
            metadata=self._json_loads(row["metadata"]) or {},
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
            pending=self._json_loads(row["pending"]) or [],
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_trace(self, row: dict) -> Trace:
        return Trace(
            id=UUID(row["id"]),
            run=UUID(row["run"]),
            capability_calls=self._json_loads(row["capability_calls"]) or [],
            file_ops=self._json_loads(row["file_ops"]) or [],
            model_version=row.get("model_version"),
            created_at=self._parse_dt(row.get("created_at")),
        )

    def _row_to_alert(self, row: dict) -> dict:
        return {
            "id": UUID(row["id"]),
            "severity": row["severity"],
            "alert_type": row["alert_type"],
            "source": row["source"],
            "message": row["message"],
            "metadata": self._json_loads(row["metadata"]) or {},
            "acknowledged_at": self._parse_dt(row.get("acknowledged_at")),
            "resolved_at": self._parse_dt(row.get("resolved_at")),
            "created_at": self._parse_dt(row.get("created_at")),
        }

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
            "cogos_delivery", "cogos_handler",
            "cogos_process_capability", "cogos_cron",
            "cogos_channel_message", "cogos_channel",
            "cogos_file_version", "cogos_file",
            "cogos_process", "cogos_capability",
            "cogos_resource", "cogos_schema",
        ]
        for t in config_tables:
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
        raise NotImplementedError

    def get_process(self, process_id: UUID) -> Process | None:
        raise NotImplementedError

    def get_process_by_name(self, name: str) -> Process | None:
        raise NotImplementedError

    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]:
        raise NotImplementedError

    def try_transition_process(
        self, process_id: UUID, from_status: ProcessStatus, to_status: ProcessStatus,
    ) -> bool:
        raise NotImplementedError

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        raise NotImplementedError

    def delete_process(self, process_id: UUID) -> bool:
        raise NotImplementedError

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        raise NotImplementedError

    def increment_retry(self, process_id: UUID) -> bool:
        raise NotImplementedError

    # ── Wait Conditions ───────────────────────────────────────

    def create_wait_condition(self, wc: WaitCondition) -> UUID:
        raise NotImplementedError

    def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None:
        raise NotImplementedError

    def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]:
        raise NotImplementedError

    def resolve_wait_condition(self, wc_id: UUID) -> None:
        raise NotImplementedError

    def resolve_wait_conditions_for_process(self, process_id: UUID) -> None:
        raise NotImplementedError

    # ── Process Capabilities ──────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        raise NotImplementedError

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]:
        raise NotImplementedError

    def delete_process_capability(self, pc_id: UUID) -> bool:
        raise NotImplementedError

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]:
        raise NotImplementedError

    # ── Handlers ──────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID:
        raise NotImplementedError

    def list_handlers(
        self, *, process_id: UUID | None = None, enabled_only: bool = False, epoch: int | None = None,
    ) -> list[Handler]:
        raise NotImplementedError

    def delete_handler(self, handler_id: UUID) -> bool:
        raise NotImplementedError

    def match_handlers(self, event_type: str) -> list[Handler]:
        raise NotImplementedError

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        raise NotImplementedError

    # ── Deliveries ────────────────────────────────────────────

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]:
        raise NotImplementedError

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]:
        raise NotImplementedError

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]:
        raise NotImplementedError

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        raise NotImplementedError

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        raise NotImplementedError

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        raise NotImplementedError

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        raise NotImplementedError

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        raise NotImplementedError

    def rollback_dispatch(
        self,
        process_id: UUID,
        run_id: UUID,
        delivery_id: UUID | None = None,
        *,
        error: str | None = None,
    ) -> None:
        raise NotImplementedError

    def get_latest_delivery_time(self, handler_id: UUID) -> datetime | None:
        raise NotImplementedError

    # ── Cron Rules ────────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID:
        raise NotImplementedError

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        raise NotImplementedError

    def delete_cron(self, cron_id: UUID) -> bool:
        raise NotImplementedError

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        raise NotImplementedError

    # ── Files ─────────────────────────────────────────────────

    def insert_file(self, f: File) -> UUID:
        raise NotImplementedError

    def get_file_by_key(self, key: str) -> File | None:
        raise NotImplementedError

    def get_file_by_id(self, file_id: UUID) -> File | None:
        raise NotImplementedError

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        raise NotImplementedError

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100,
    ) -> list[tuple[str, str]]:
        raise NotImplementedError

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200,
    ) -> list[str]:
        raise NotImplementedError

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool:
        raise NotImplementedError

    def delete_file(self, file_id: UUID) -> bool:
        raise NotImplementedError

    def bulk_upsert_files(
        self,
        files: list[tuple[str, str, str, list[str]]],
        *,
        batch_size: int = 100,
    ) -> int:
        raise NotImplementedError

    # ── File Versions ─────────────────────────────────────────

    def insert_file_version(self, fv: FileVersion) -> None:
        raise NotImplementedError

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None:
        raise NotImplementedError

    def get_max_file_version(self, file_id: UUID) -> int:
        raise NotImplementedError

    def list_file_versions(self, file_id: UUID) -> list[FileVersion]:
        raise NotImplementedError

    def set_active_file_version(self, file_id: UUID, version: int) -> None:
        raise NotImplementedError

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        raise NotImplementedError

    def delete_file_version(self, file_id: UUID, version: int) -> bool:
        raise NotImplementedError

    # ── Capabilities ──────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID:
        raise NotImplementedError

    def get_capability(self, cap_id: UUID) -> Capability | None:
        raise NotImplementedError

    def get_capability_by_name(self, name: str) -> Capability | None:
        raise NotImplementedError

    def get_capability_by_handler(self, handler: str) -> Capability | None:
        raise NotImplementedError

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]:
        raise NotImplementedError

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]:
        raise NotImplementedError

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, resource: Resource) -> str:
        raise NotImplementedError

    def list_resources(self) -> list[Resource]:
        raise NotImplementedError

    # ── Runs ──────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        raise NotImplementedError

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
        raise NotImplementedError

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int:
        raise NotImplementedError

    def get_run(self, run_id: UUID) -> Run | None:
        raise NotImplementedError

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        raise NotImplementedError

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

    def list_file_mutations(self, run_id: UUID) -> list[dict]:
        raise NotImplementedError

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        raise NotImplementedError

    # ── Traces ────────────────────────────────────────────────

    def create_trace(self, trace: Trace) -> UUID:
        raise NotImplementedError

    # ── Request Traces & Spans ────────────────────────────────

    def create_request_trace(self, trace: RequestTrace) -> UUID:
        raise NotImplementedError

    def get_request_trace(self, trace_id: UUID) -> RequestTrace | None:
        raise NotImplementedError

    def create_span(self, span: Span) -> UUID:
        raise NotImplementedError

    def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool:
        raise NotImplementedError

    def list_spans(self, trace_id: UUID) -> list[Span]:
        raise NotImplementedError

    def create_span_event(self, event: SpanEvent) -> UUID:
        raise NotImplementedError

    def list_span_events(self, span_id: UUID) -> list[SpanEvent]:
        raise NotImplementedError

    def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]:
        raise NotImplementedError

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
        raise NotImplementedError

    def get_schema(self, schema_id: UUID) -> Schema | None:
        raise NotImplementedError

    def get_schema_by_name(self, name: str) -> Schema | None:
        raise NotImplementedError

    def list_schemas(self) -> list[Schema]:
        raise NotImplementedError

    # ── Channels ──────────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> UUID:
        raise NotImplementedError

    def get_channel(self, channel_id: UUID) -> Channel | None:
        raise NotImplementedError

    def get_channel_by_name(self, name: str) -> Channel | None:
        raise NotImplementedError

    def list_channels(self, *, owner_process: UUID | None = None, limit: int = 0) -> list[Channel]:
        raise NotImplementedError

    def close_channel(self, channel_id: UUID) -> bool:
        raise NotImplementedError

    # ── Channel Messages ──────────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        raise NotImplementedError

    def get_channel_message(self, message_id: UUID) -> ChannelMessage | None:
        raise NotImplementedError

    def list_channel_messages(
        self, channel_id: UUID | None = None, *, limit: int = 100, since: datetime | None = None,
    ) -> list[ChannelMessage]:
        raise NotImplementedError

    # ── Discord Metadata ──────────────────────────────────────

    def upsert_discord_guild(self, guild: DiscordGuild) -> None:
        raise NotImplementedError

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
        raise NotImplementedError

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
        raise NotImplementedError

    def delete_discord_guild(self, guild_id: str) -> None:
        raise NotImplementedError

    def upsert_discord_channel(self, channel: DiscordChannel) -> None:
        raise NotImplementedError

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
        raise NotImplementedError

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
        raise NotImplementedError

    def delete_discord_channel(self, channel_id: str) -> None:
        raise NotImplementedError

    # ── Executors ─────────────────────────────────────────────

    def register_executor(self, executor: Executor) -> UUID:
        raise NotImplementedError

    def get_executor(self, executor_id: str) -> Executor | None:
        raise NotImplementedError

    def get_executor_by_id(self, id: UUID) -> Executor | None:
        raise NotImplementedError

    def list_executors(self, status: ExecutorStatus | None = None) -> list[Executor]:
        raise NotImplementedError

    def select_executor(
        self,
        required_tags: list[str] | None = None,
        preferred_tags: list[str] | None = None,
    ) -> Executor | None:
        raise NotImplementedError

    def heartbeat_executor(
        self,
        executor_id: str,
        status: ExecutorStatus = ExecutorStatus.IDLE,
        current_run_id: UUID | None = None,
        resource_usage: dict | None = None,
    ) -> bool:
        raise NotImplementedError

    def update_executor_status(
        self, executor_id: str, status: ExecutorStatus, current_run_id: UUID | None = None,
    ) -> None:
        raise NotImplementedError

    def delete_executor(self, executor_id: str) -> None:
        raise NotImplementedError

    def reap_stale_executors(self, heartbeat_interval_s: int = 30) -> int:
        raise NotImplementedError

    # ── Executor Tokens ───────────────────────────────────────

    def create_executor_token(self, token: ExecutorToken) -> UUID:
        raise NotImplementedError

    def get_executor_token_by_hash(self, token_hash: str) -> ExecutorToken | None:
        raise NotImplementedError

    def list_executor_tokens(self) -> list[ExecutorToken]:
        raise NotImplementedError

    def revoke_executor_token(self, name: str) -> bool:
        raise NotImplementedError

    # ── Lifecycle ─────────────────────────────────────────────

    def reload(self) -> None:
        pass

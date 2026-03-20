"""CogOS repository — CRUD for all CogOS tables via RDS Data API."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import boto3

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
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    RequestTrace,
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
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild

logger = logging.getLogger(__name__)


class Repository:
    """Synchronous CogOS repository using RDS Data API."""

    def __init__(
        self,
        client: Any,
        resource_arn: str,
        secret_arn: str,
        database: str,
        region: str = "us-east-1",
    ) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database
        self._region = region
        self._ingress_queue_url = os.environ.get("COGOS_INGRESS_QUEUE_URL", "")

    def _nudge_ingress(self, *, process_id: UUID | None = None) -> None:
        """Send a message to the ingress SQS queue to trigger immediate dispatch.

        When *process_id* is provided the ingress Lambda will dispatch that
        specific process instead of relying on weighted random selection, which
        can starve low-priority processes.
        """
        if not self._ingress_queue_url:
            return
        try:
            import json as _json

            body: dict = {"source": "channel_message"}
            if process_id is not None:
                body["process_id"] = str(process_id)
            sqs = boto3.client("sqs", region_name=self._region)
            sqs.send_message(
                QueueUrl=self._ingress_queue_url,
                MessageBody=_json.dumps(body),
                MessageGroupId="ingress-wake",
                MessageDeduplicationId=str(int(time.time())),
            )
        except Exception:
            logger.debug("Failed to nudge ingress queue", exc_info=True)

    @classmethod
    def create(
        cls,
        resource_arn: str | None = None,
        secret_arn: str | None = None,
        database: str | None = None,
        region: str | None = None,
    ) -> Repository:
        resource_arn = resource_arn or os.environ.get("DB_RESOURCE_ARN", "") or os.environ.get("DB_CLUSTER_ARN", "")
        secret_arn = secret_arn or os.environ.get("DB_SECRET_ARN", "")
        database = database or os.environ.get("DB_NAME", "")
        region = region or os.environ.get("AWS_REGION", "us-east-1")

        if not all([resource_arn, secret_arn, database]):
            raise ValueError(
                "Must provide resource_arn, secret_arn, and database "
                "via arguments or environment variables "
                "(DB_RESOURCE_ARN/DB_CLUSTER_ARN, DB_SECRET_ARN, DB_NAME)"
            )

        client = boto3.client("rds-data", region_name=region)
        return cls(client, resource_arn, secret_arn, database, region)

    # ═══════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════

    def _execute(self, sql: str, params: list[dict] | None = None) -> dict:
        kwargs: dict[str, Any] = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "includeResultMetadata": True,
        }
        if params:
            kwargs["parameters"] = params
        try:
            return self._client.execute_statement(**kwargs)
        except Exception:
            # Log the failing SQL + param names/types for debugging
            import re
            jsonb_params = set(re.findall(r":(\w+)::jsonb", sql))
            if jsonb_params and params:
                for p in params:
                    name = p.get("name", "?")
                    if name in jsonb_params:
                        val = p.get("value", {})
                        sv = val.get("stringValue")
                        if sv is not None:
                            logger.error(
                                "JSONB param %s value (first 200 chars): %s",
                                name, sv[:200],
                            )
            logger.error("Failing SQL: %s", sql[:500])
            raise

    def _param(self, name: str, value: Any) -> dict:
        param: dict[str, Any] = {"name": name}
        if value is None:
            param["value"] = {"isNull": True}
        elif isinstance(value, bool):
            param["value"] = {"booleanValue": value}
        elif isinstance(value, int):
            param["value"] = {"longValue": value}
        elif isinstance(value, float):
            param["value"] = {"doubleValue": value}
        elif isinstance(value, Decimal):
            param["value"] = {"stringValue": str(value)}
        elif isinstance(value, UUID):
            param["value"] = {"stringValue": str(value)}
            param["typeHint"] = "UUID"
        elif isinstance(value, datetime):
            param["value"] = {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S.%f")}
            param["typeHint"] = "TIMESTAMP"
        elif isinstance(value, (dict, list)):
            param["value"] = {"stringValue": json.dumps(value, default=str)}
        elif isinstance(value, str):
            param["value"] = {"stringValue": value}
        else:
            # Non-standard type (Pydantic model, enum, etc.).  Use str()
            # which is correct for text columns.  If this value is bound to
            # a ::jsonb column, the _execute error handler will log it.
            logger.debug(
                "Param %s has non-standard type %s; converting via str()",
                name, type(value).__name__,
            )
            param["value"] = {"stringValue": str(value)}
        return param

    @staticmethod
    def _jsonb_safe(value: Any) -> dict | list | None:
        """Ensure *value* is a dict, list, or None suitable for a ::jsonb column.

        If value is already the right type, return it unchanged.  Otherwise
        round-trip through JSON to produce a clean dict/list.  This prevents
        ``invalid input syntax for type json`` errors when non-serializable
        objects (Pydantic models, enums, etc.) leak into jsonb parameters.
        """
        if value is None or isinstance(value, (dict, list)):
            return value
        # Last-resort: try to convert via JSON round-trip
        try:
            return json.loads(json.dumps(value, default=str))
        except (TypeError, ValueError):
            logger.warning("_jsonb_safe: could not serialize %s, wrapping as string", type(value).__name__)
            return {"_raw": str(value)}

    def _extract_value(self, cell: dict) -> Any:
        if "isNull" in cell and cell["isNull"]:
            return None
        if "stringValue" in cell:
            return cell["stringValue"]
        if "longValue" in cell:
            return cell["longValue"]
        if "doubleValue" in cell:
            return cell["doubleValue"]
        if "booleanValue" in cell:
            return cell["booleanValue"]
        return None

    def _rows_to_dicts(self, response: dict) -> list[dict]:
        if "records" not in response or not response["records"]:
            return []
        column_names = [col["name"] for col in response.get("columnMetadata", [])]
        rows = []
        for record in response["records"]:
            row = {}
            for col_name, cell in zip(column_names, record, strict=False):
                row[col_name] = self._extract_value(cell)
            rows.append(row)
        return rows

    def _first_row(self, response: dict) -> dict | None:
        rows = self._rows_to_dicts(response)
        return rows[0] if rows else None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        api_params = [self._param(k, v) for k, v in params.items()] if params else None
        return self._rows_to_dicts(self._execute(sql, api_params))

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        api_params = [self._param(k, v) for k, v in params.items()] if params else None
        response = self._execute(sql, api_params)
        return response.get("numberOfRecordsUpdated", 0)

    # ═══════════════════════════════════════════════════════════
    # BULK CLEAR
    # ═══════════════════════════════════════════════════════════

    # Deletion order respects FK constraints: children before parents.
    _ALL_TABLES = [
        "cogos_span_event", "cogos_span", "cogos_request_trace",
        "cogos_trace", "cogos_delivery", "cogos_channel_message",
        "cogos_run", "cogos_handler", "cogos_process_capability",
        "alerts", "cron",
        "cogos_file_version", "cogos_file",
        "cogos_channel", "cogos_schema",
        "cogos_process", "cogos_capability",
    ]

    _CONFIG_TABLES = [
        "cogos_span_event", "cogos_span", "cogos_request_trace",
        "cogos_trace", "cogos_delivery", "cogos_channel_message",
        "cogos_run", "cogos_handler", "cogos_process_capability",
        "cron",
    ]

    _CONFIG_TABLES_FINAL = ["cogos_process", "cogos_capability"]

    def clear_all(self) -> None:
        """Delete all rows from every CogOS table."""
        for table in self._ALL_TABLES:
            self.execute(f"DELETE FROM {table}")

    def clear_config(self) -> None:
        """Clear config/process/run/message tables, preserving file and channel definitions."""
        for table in self._CONFIG_TABLES:
            self.execute(f"DELETE FROM {table}")
        # Nullify FK references from channels before deleting processes
        self.execute(
            "UPDATE cogos_channel SET owner_process = NULL "
            "WHERE owner_process IS NOT NULL"
        )
        for table in self._CONFIG_TABLES_FINAL:
            self.execute(f"DELETE FROM {table}")

    def delete_files_by_prefixes(self, prefixes: list[str]) -> int:
        """Delete files whose key starts with any of the given prefixes."""
        total = 0
        for prefix in prefixes:
            params = {"prefix": prefix + "%"}
            self.execute(
                "DELETE FROM cogos_file_version WHERE file_id IN "
                "(SELECT id FROM cogos_file WHERE key LIKE :prefix)",
                params,
            )
            total += self.execute(
                "DELETE FROM cogos_file WHERE key LIKE :prefix",
                params,
            )
        return total

    @staticmethod
    def _json_field(row: dict, key: str, default: Any = None) -> Any:
        val = row.get(key, default)
        if isinstance(val, str):
            return json.loads(val)
        return val if val is not None else default

    @staticmethod
    def _ts(row: dict, key: str) -> datetime | None:
        v = row.get(key)
        if not v:
            return None
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # ═══════════════════════════════════════════════════════════
    # EPOCH
    # ═══════════════════════════════════════════════════════════

    @property
    def reboot_epoch(self) -> int:
        meta = self.get_meta("reboot_epoch")
        if meta and meta.get("value"):
            return int(meta["value"])
        return 0

    def increment_epoch(self) -> int:
        new_epoch = self.reboot_epoch + 1
        self.set_meta("reboot_epoch", str(new_epoch))
        return new_epoch

    # ═══════════════════════════════════════════════════════════
    # OPERATIONS
    # ═══════════════════════════════════════════════════════════

    def add_operation(self, op: CogosOperation) -> UUID:
        now = op.created_at or datetime.now(timezone.utc)
        op.metadata = self._jsonb_safe(op.metadata) or {}
        self._execute(
            """INSERT INTO cogos_operation (id, epoch, type, metadata, created_at)
               VALUES (:id, :epoch, :type, :metadata::jsonb, :created_at)""",
            [
                self._param("id", op.id),
                self._param("epoch", op.epoch),
                self._param("type", op.type),
                self._param("metadata", op.metadata),
                self._param("created_at", now),
            ],
        )
        return op.id

    def list_operations(self, limit: int = 50) -> list[CogosOperation]:
        response = self._execute(
            "SELECT * FROM cogos_operation ORDER BY created_at DESC LIMIT :limit",
            [self._param("limit", limit)],
        )
        result = []
        for row in self._rows_to_dicts(response):
            result.append(CogosOperation(
                id=UUID(row["id"]),
                epoch=row.get("epoch", 0),
                type=row.get("type", ""),
                metadata=self._json_field(row, "metadata", {}),
                created_at=self._ts(row, "created_at"),
            ))
        return result

    # ═══════════════════════════════════════════════════════════
    # PROCESSES
    # ═══════════════════════════════════════════════════════════

    def upsert_process(self, p: Process) -> UUID:
        if not p.epoch:
            p.epoch = self.reboot_epoch
        p.model_constraints = self._jsonb_safe(p.model_constraints) or {}
        p.return_schema = self._jsonb_safe(p.return_schema)
        p.metadata = self._jsonb_safe(p.metadata) or {}
        response = self._execute(
            """INSERT INTO cogos_process
                   (id, name, mode, content, priority, resources, runner, executor,
                    status, runnable_since, parent_process, preemptible,
                    model, model_constraints, return_schema,
                    idle_timeout_ms, max_duration_ms, max_retries, retry_count, retry_backoff_ms,
                    clear_context, tty, metadata, epoch)
               VALUES (:id, :name, :mode, :content, :priority, :resources::jsonb, :runner, :executor,
                       :status, :runnable_since, :parent_process, :preemptible,
                       :model, :model_constraints::jsonb, :return_schema::jsonb,
                       :idle_timeout_ms, :max_duration_ms, :max_retries, :retry_count, :retry_backoff_ms,
                       :clear_context, :tty, :metadata::jsonb, :epoch)
               ON CONFLICT (name) DO UPDATE SET
                   mode = EXCLUDED.mode, content = EXCLUDED.content,
                   priority = EXCLUDED.priority,
                   status = EXCLUDED.status,
                   resources = EXCLUDED.resources, runner = EXCLUDED.runner,
                   executor = EXCLUDED.executor,
                   preemptible = EXCLUDED.preemptible, model = EXCLUDED.model,
                   model_constraints = EXCLUDED.model_constraints,
                   return_schema = EXCLUDED.return_schema,
                   idle_timeout_ms = EXCLUDED.idle_timeout_ms,
                   max_duration_ms = EXCLUDED.max_duration_ms,
                   max_retries = EXCLUDED.max_retries,
                   retry_backoff_ms = EXCLUDED.retry_backoff_ms,
                   clear_context = EXCLUDED.clear_context,
                   tty = EXCLUDED.tty,
                   metadata = EXCLUDED.metadata,
                   epoch = EXCLUDED.epoch,
                   updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", p.id),
                self._param("name", p.name),
                self._param("mode", p.mode.value),
                self._param("content", p.content),
                self._param("priority", p.priority),
                self._param("resources", [str(r) for r in p.resources]),
                self._param("runner", p.runner),
                self._param("executor", p.executor),
                self._param("status", p.status.value),
                self._param("runnable_since", p.runnable_since),
                self._param("parent_process", p.parent_process),
                self._param("preemptible", p.preemptible),
                self._param("model", p.model),
                self._param("model_constraints", p.model_constraints),
                self._param("return_schema", p.return_schema),
                self._param("idle_timeout_ms", p.idle_timeout_ms),
                self._param("max_duration_ms", p.max_duration_ms),
                self._param("max_retries", p.max_retries),
                self._param("retry_count", p.retry_count),
                self._param("retry_backoff_ms", p.retry_backoff_ms),
                self._param("clear_context", p.clear_context),
                self._param("tty", p.tty),
                self._param("metadata", p.metadata),
                self._param("epoch", p.epoch),
            ],
        )
        row = self._first_row(response)
        if row:
            p.created_at = self._ts(row, "created_at")
            p.updated_at = self._ts(row, "updated_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert process")

    def get_process(self, process_id: UUID) -> Process | None:
        response = self._execute(
            "SELECT * FROM cogos_process WHERE id = :id",
            [self._param("id", process_id)],
        )
        row = self._first_row(response)
        return self._process_from_row(row) if row else None

    def get_process_by_name(self, name: str) -> Process | None:
        response = self._execute(
            "SELECT * FROM cogos_process WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._process_from_row(row) if row else None

    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions = []
        params = [self._param("limit", limit)]
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params.append(self._param("epoch", effective_epoch))
        if status:
            conditions.append("status = :status")
            params.append(self._param("status", status.value))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        response = self._execute(
            f"SELECT * FROM cogos_process{where} ORDER BY name LIMIT :limit",
            params,
        )
        return [self._process_from_row(r) for r in self._rows_to_dicts(response)]

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        extra = ""
        if status == ProcessStatus.RUNNABLE:
            extra = ", runnable_since = COALESCE(runnable_since, now())"
        elif status in (ProcessStatus.RUNNING, ProcessStatus.WAITING, ProcessStatus.COMPLETED):
            extra = ", runnable_since = NULL"
        response = self._execute(
            f"UPDATE cogos_process SET status = :status{extra}, updated_at = now() WHERE id = :id",
            [self._param("id", process_id), self._param("status", status.value)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        response = self._execute(
            """SELECT * FROM cogos_process WHERE status = 'runnable' AND epoch = :epoch
               ORDER BY priority DESC, runnable_since ASC NULLS LAST
               LIMIT :limit""",
            [self._param("epoch", self.reboot_epoch), self._param("limit", limit)],
        )
        return [self._process_from_row(r) for r in self._rows_to_dicts(response)]

    def increment_retry(self, process_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_process SET retry_count = retry_count + 1, updated_at = now() WHERE id = :id",
            [self._param("id", process_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _process_from_row(self, row: dict) -> Process:
        resources_raw = self._json_field(row, "resources", [])
        resources = [UUID(r) for r in resources_raw] if resources_raw else []
        return Process(
            id=UUID(row["id"]),
            epoch=row.get("epoch", 0),
            name=row["name"],
            mode=ProcessMode(row["mode"]),
            content=row.get("content", ""),
            priority=row.get("priority", 0.0),
            resources=resources,
            runner=row.get("runner", "lambda"),
            executor=row.get("executor", "llm"),
            status=ProcessStatus(row["status"]),
            runnable_since=self._ts(row, "runnable_since"),
            parent_process=UUID(row["parent_process"]) if row.get("parent_process") else None,
            preemptible=row.get("preemptible", False),
            model=row.get("model"),
            model_constraints=self._json_field(row, "model_constraints", {}),
            return_schema=self._json_field(row, "return_schema"),
            idle_timeout_ms=row.get("idle_timeout_ms"),
            max_duration_ms=row.get("max_duration_ms"),
            max_retries=row.get("max_retries", 0),
            retry_count=row.get("retry_count", 0),
            retry_backoff_ms=row.get("retry_backoff_ms"),
            clear_context=row.get("clear_context", False),
            tty=row.get("tty", False),
            metadata=self._json_field(row, "metadata", {}),
            created_at=self._ts(row, "created_at"),
            updated_at=self._ts(row, "updated_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # PROCESS CAPABILITIES
    # ═══════════════════════════════════════════════════════════

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        pc.config = self._jsonb_safe(pc.config)
        response = self._execute(
            """INSERT INTO cogos_process_capability (id, process, capability, name, config, epoch)
               VALUES (:id, :process, :capability, :name, :config::jsonb, :epoch)
               ON CONFLICT (process, name) DO UPDATE SET
                   capability = EXCLUDED.capability,
                   config = EXCLUDED.config
               RETURNING id""",
            [
                self._param("id", pc.id),
                self._param("process", pc.process),
                self._param("capability", pc.capability),
                self._param("name", pc.name),
                self._param("config", pc.config),
                self._param("epoch", pc.epoch),
            ],
        )
        row = self._first_row(response)
        return UUID(row["id"]) if row else pc.id

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]:
        response = self._execute(
            "SELECT * FROM cogos_process_capability WHERE process = :process",
            [self._param("process", process_id)],
        )
        return [
            ProcessCapability(
                id=UUID(r["id"]),
                process=UUID(r["process"]),
                capability=UUID(r["capability"]),
                name=r.get("name", ""),
                config=self._json_field(r, "config"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def delete_process(self, process_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cogos_process WHERE id = :id",
            [self._param("id", process_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def delete_process_capability(self, pc_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cogos_process_capability WHERE id = :id",
            [self._param("id", pc_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]:
        """Return processes granted a specific capability with grant metadata."""
        response = self._execute(
            """SELECT p.id AS process_id, p.name AS process_name, p.status AS process_status,
                      pc.name AS grant_name, pc.config
               FROM cogos_process_capability pc
               JOIN cogos_process p ON p.id = pc.process
               WHERE pc.capability = :capability
               ORDER BY p.name""",
            [self._param("capability", capability_id)],
        )
        rows = self._rows_to_dicts(response)
        return [
            {
                "process_id": str(r["process_id"]),
                "process_name": r["process_name"],
                "process_status": r["process_status"],
                "grant_name": r.get("grant_name", ""),
                "config": self._json_field(r, "config"),
            }
            for r in rows
        ]

    # ═══════════════════════════════════════════════════════════
    # HANDLERS
    # ═══════════════════════════════════════════════════════════

    def create_handler(self, h: Handler) -> UUID:
        if h.channel is not None:
            # Channel-based handler: upsert by (process, channel)
            response = self._execute(
                """INSERT INTO cogos_handler (id, process, channel, enabled, epoch)
                   VALUES (:id, :process, :channel, :enabled, :epoch)
                   ON CONFLICT (process, channel) DO UPDATE SET enabled = EXCLUDED.enabled, epoch = EXCLUDED.epoch
                   RETURNING id, created_at""",
                [
                    self._param("id", h.id),
                    self._param("process", h.process),
                    self._param("channel", h.channel),
                    self._param("enabled", h.enabled),
                    self._param("epoch", h.epoch),
                ],
            )
        else:
            raise ValueError("Handler must have a channel FK set")
        row = self._first_row(response)
        if row:
            h.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        return h.id

    def list_handlers(
        self, *, process_id: UUID | None = None, enabled_only: bool = False, epoch: int | None = None,
    ) -> list[Handler]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions = []
        params = []
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params.append(self._param("epoch", effective_epoch))
        if process_id:
            conditions.append("process = :process")
            params.append(self._param("process", process_id))
        if enabled_only:
            conditions.append("enabled = TRUE")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        response = self._execute(
            f"SELECT * FROM cogos_handler {where} ORDER BY created_at",
            params or None,
        )
        return [self._handler_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_handler(self, handler_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cogos_handler WHERE id = :id",
            [self._param("id", handler_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def match_handlers(self, event_type: str) -> list[Handler]:
        """Legacy event-era compatibility stub.

        The active runtime binds handlers to channels, not event patterns, so
        old event-pattern matching no longer exists. Keep this method as a
        no-op for older callers that still import it.
        """
        # Legacy API: channel-based code should call match_handlers_by_channel().
        return []

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        """Find enabled handlers subscribed to a specific channel."""
        response = self._execute(
            """SELECT * FROM cogos_handler
               WHERE enabled = TRUE AND channel = :channel""",
            [self._param("channel", channel_id)],
        )
        return [self._handler_from_row(r) for r in self._rows_to_dicts(response)]

    def _handler_from_row(self, r: dict) -> Handler:
        return Handler(
            id=UUID(r["id"]),
            epoch=r.get("epoch", 0),
            process=UUID(r["process"]),
            channel=UUID(r["channel"]) if r.get("channel") else None,
            enabled=r["enabled"],
            created_at=self._ts(r, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # DELIVERIES
    # ═══════════════════════════════════════════════════════════

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]:
        response = self._execute(
            """WITH inserted AS (
                   INSERT INTO cogos_delivery (id, message, handler, status, run, trace_id, epoch)
                   VALUES (:id, :message, :handler, :status, :run, :trace_id, :epoch)
                   ON CONFLICT (message, handler) DO NOTHING
                   RETURNING id, created_at, TRUE AS inserted
               )
               SELECT id, created_at, inserted FROM inserted
               UNION ALL
               SELECT id, created_at, FALSE AS inserted
               FROM cogos_delivery
               WHERE message = :message AND handler = :handler
                 AND NOT EXISTS (SELECT 1 FROM inserted)
               LIMIT 1""",
            [
                self._param("id", ed.id),
                self._param("message", ed.message),
                self._param("handler", ed.handler),
                self._param("status", ed.status.value),
                self._param("run", ed.run),
                self._param("trace_id", ed.trace_id),
                self._param("epoch", ed.epoch),
            ],
        )
        row = self._first_row(response)
        if row:
            ed.created_at = self._ts(row, "created_at")
            return UUID(row["id"]), bool(row.get("inserted", False))
        return ed.id, False

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]:
        response = self._execute(
            """SELECT ed.* FROM cogos_delivery ed
               JOIN cogos_handler h ON h.id = ed.handler
               WHERE h.process = :process AND ed.status = 'pending'
               ORDER BY ed.created_at ASC""",
            [self._param("process", process_id)],
        )
        return [self._delivery_from_row(r) for r in self._rows_to_dicts(response)]

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions = []
        params = [self._param("limit", limit)]
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params.append(self._param("epoch", effective_epoch))
        if message_id is not None:
            conditions.append("message = :message")
            params.append(self._param("message", message_id))
        if handler_id is not None:
            conditions.append("handler = :handler")
            params.append(self._param("handler", handler_id))
        if run_id is not None:
            conditions.append("run = :run")
            params.append(self._param("run", run_id))

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        response = self._execute(
            f"""SELECT * FROM cogos_delivery
                {where}
                ORDER BY created_at DESC
                LIMIT :limit""",
            params,
        )
        return [self._delivery_from_row(r) for r in self._rows_to_dicts(response)]

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        row = self._first_row(self._execute(
            """SELECT 1
               FROM cogos_delivery ed
               JOIN cogos_handler h ON h.id = ed.handler
               WHERE h.process = :process AND ed.status = 'pending'
               LIMIT 1""",
            [self._param("process", process_id)],
        ))
        return row is not None

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_delivery SET status = 'delivered', run = :run WHERE id = :id",
            [self._param("id", delivery_id), self._param("run", run_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_delivery SET status = 'queued', run = :run WHERE id = :id",
            [self._param("id", delivery_id), self._param("run", run_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_delivery SET status = 'pending', run = NULL WHERE id = :id",
            [self._param("id", delivery_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        response = self._execute(
            """UPDATE cogos_delivery
               SET status = 'delivered'
               WHERE run = :run AND status = 'queued'""",
            [self._param("run", run_id)],
        )
        return response.get("numberOfRecordsUpdated", 0)

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
        current = self.get_process(process_id)
        if current and current.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            self.update_process_status(process_id, ProcessStatus.RUNNABLE)

    # ═══════════════════════════════════════════════════════════
    # CRON RULES
    # ═══════════════════════════════════════════════════════════

    def upsert_cron(self, c: Cron) -> UUID:
        c.payload = self._jsonb_safe(c.payload) or {}
        # Check for existing rule with same expression + channel name
        existing = self._first_row(self._execute(
            "SELECT id FROM cron WHERE cron_expression = :expr AND channel_name = :channel_name",
            [self._param("expr", c.expression), self._param("channel_name", c.channel_name)],
        ))
        if existing:
            c.id = UUID(existing["id"])
            self._execute(
                """UPDATE cron SET metadata = :payload::jsonb, enabled = :enabled
                   WHERE id = :id""",
                [
                    self._param("id", c.id),
                    self._param("payload", c.payload),
                    self._param("enabled", c.enabled),
                ],
            )
            return c.id

        response = self._execute(
            """INSERT INTO cron (id, cron_expression, channel_name, metadata, enabled)
               VALUES (:id, :expression, :channel_name, :payload::jsonb, :enabled)
               RETURNING id, created_at""",
            [
                self._param("id", c.id),
                self._param("expression", c.expression),
                self._param("channel_name", c.channel_name),
                self._param("payload", c.payload),
                self._param("enabled", c.enabled),
            ],
        )
        row = self._first_row(response)
        if row:
            c.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        return c.id

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        where = "WHERE enabled = TRUE" if enabled_only else ""
        response = self._execute(
            f"SELECT * FROM cron {where} ORDER BY cron_expression",
        )
        return [
            Cron(
                id=UUID(r["id"]),
                expression=r["cron_expression"],
                channel_name=r["channel_name"],
                payload=self._json_field(r, "metadata", {}),
                enabled=r.get("enabled", True),
                created_at=self._ts(r, "created_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def delete_cron(self, cron_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cron WHERE id = :id",
            [self._param("id", cron_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        response = self._execute(
            "UPDATE cron SET enabled = :enabled WHERE id = :id",
            [self._param("id", cron_id), self._param("enabled", enabled)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    # ═══════════════════════════════════════════════════════════
    # FILES
    # ═══════════════════════════════════════════════════════════

    def insert_file(self, f: File) -> UUID:
        f.includes = self._jsonb_safe(f.includes) or []
        response = self._execute(
            """INSERT INTO cogos_file (id, key, includes)
               VALUES (:id, :key, :includes::jsonb)
               ON CONFLICT (key) DO UPDATE SET
                   includes = EXCLUDED.includes, updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", f.id),
                self._param("key", f.key),
                self._param("includes", f.includes),
            ],
        )
        row = self._first_row(response)
        if row:
            f.created_at = self._ts(row, "created_at")
            f.updated_at = self._ts(row, "updated_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to insert file")

    def get_file_by_key(self, key: str) -> File | None:
        response = self._execute(
            "SELECT * FROM cogos_file WHERE key = :key",
            [self._param("key", key)],
        )
        row = self._first_row(response)
        return self._file_from_row(row) if row else None

    def get_file_by_id(self, file_id: UUID) -> File | None:
        response = self._execute(
            "SELECT * FROM cogos_file WHERE id = :id",
            [self._param("id", file_id)],
        )
        row = self._first_row(response)
        return self._file_from_row(row) if row else None

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        if prefix:
            response = self._execute(
                "SELECT * FROM cogos_file WHERE key LIKE :prefix ORDER BY key LIMIT :limit",
                [self._param("prefix", prefix + "%"), self._param("limit", limit)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_file ORDER BY key LIMIT :limit",
                [self._param("limit", limit)],
            )
        return [self._file_from_row(r) for r in self._rows_to_dicts(response)]

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100
    ) -> list[tuple[str, str]]:
        """Search active file versions by regex pattern. Returns (key, content) tuples."""
        if prefix:
            response = self._execute(
                """SELECT f.key, fv.content
                   FROM cogos_file f
                   JOIN cogos_file_version fv ON fv.file_id = f.id
                   WHERE fv.is_active = true
                     AND f.key LIKE :prefix
                     AND fv.content ~ :pattern
                   ORDER BY f.key
                   LIMIT :limit""",
                [
                    self._param("prefix", prefix + "%"),
                    self._param("pattern", pattern),
                    self._param("limit", limit),
                ],
            )
        else:
            response = self._execute(
                """SELECT f.key, fv.content
                   FROM cogos_file f
                   JOIN cogos_file_version fv ON fv.file_id = f.id
                   WHERE fv.is_active = true
                     AND fv.content ~ :pattern
                   ORDER BY f.key
                   LIMIT :limit""",
                [
                    self._param("pattern", pattern),
                    self._param("limit", limit),
                ],
            )
        rows = self._rows_to_dicts(response)
        return [(r["key"], r["content"]) for r in rows]

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        response = self._execute(
            "UPDATE cogos_file_version SET content = :content WHERE file = :file_id AND version = :version",
            [
                self._param("file_id", file_id),
                self._param("version", version),
                self._param("content", content),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool:
        response = self._execute(
            "UPDATE cogos_file SET includes = :includes::jsonb, updated_at = now() WHERE id = :id",
            [self._param("id", file_id), self._param("includes", self._jsonb_safe(includes) or [])],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def bulk_upsert_files(
        self,
        files: list[tuple[str, str, str, list[str]]],
        *,
        batch_size: int = 100,
    ) -> int:
        """Bulk upsert files using batch_execute_statement.

        Each entry is (key, content, source, includes).
        Returns the number of files upserted.
        """
        if not files:
            return 0

        from uuid import uuid4

        # Pre-generate IDs and models
        file_records = []
        for key, content, source, includes in files:
            file_id = uuid4()
            fv_id = uuid4()
            file_records.append({
                "file_id": file_id,
                "fv_id": fv_id,
                "key": key,
                "content": content,
                "source": source,
                "includes": self._jsonb_safe(includes) or [],
            })

        base_kwargs = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
        }

        # Batch insert into cogos_file
        file_sql = """INSERT INTO cogos_file (id, key, includes)
                      VALUES (:id, :key, :includes::jsonb)
                      ON CONFLICT (key) DO UPDATE SET
                          includes = EXCLUDED.includes, updated_at = now()"""

        for i in range(0, len(file_records), batch_size):
            chunk = file_records[i : i + batch_size]
            param_sets = [
                [
                    self._param("id", r["file_id"]),
                    self._param("key", r["key"]),
                    self._param("includes", r["includes"]),
                ]
                for r in chunk
            ]
            self._client.batch_execute_statement(
                **base_kwargs, sql=file_sql, parameterSets=param_sets
            )

        # Now get actual file IDs (ON CONFLICT keeps existing ID, not ours)
        # Use string_to_array to batch-lookup keys efficiently
        for i in range(0, len(file_records), batch_size):
            chunk = file_records[i : i + batch_size]
            keys_str = "\n".join(r["key"] for r in chunk)
            response = self._execute(
                "SELECT id, key FROM cogos_file WHERE key = ANY(string_to_array(:keys, chr(10)))",
                [self._param("keys", keys_str)],
            )
            key_to_id = {
                row["key"]: UUID(row["id"])
                for row in self._rows_to_dicts(response)
            }
            for r in chunk:
                r["file_id"] = key_to_id.get(r["key"], r["file_id"])

        # Batch insert into cogos_file_version (version=1, is_active=true)
        fv_sql = """INSERT INTO cogos_file_version
                        (id, file_id, version, read_only, content, source, is_active)
                    VALUES (:id, :file_id, 1, false, :content, :source, true)
                    ON CONFLICT (file_id, version) DO UPDATE SET
                        content = EXCLUDED.content,
                        source = EXCLUDED.source,
                        is_active = EXCLUDED.is_active"""

        for i in range(0, len(file_records), batch_size):
            chunk = file_records[i : i + batch_size]
            param_sets = [
                [
                    self._param("id", r["fv_id"]),
                    self._param("file_id", r["file_id"]),
                    self._param("content", r["content"]),
                    self._param("source", r["source"]),
                ]
                for r in chunk
            ]
            self._client.batch_execute_statement(
                **base_kwargs, sql=fv_sql, parameterSets=param_sets
            )

        return len(file_records)

    def delete_file(self, file_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cogos_file WHERE id = :id",
            [self._param("id", file_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _file_from_row(self, row: dict) -> File:
        return File(
            id=UUID(row["id"]),
            key=row["key"],
            includes=self._json_field(row, "includes", []),
            created_at=self._ts(row, "created_at"),
            updated_at=self._ts(row, "updated_at"),
        )

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        """Convert a glob pattern to a Postgres regex.

        * = one path segment (no slashes)
        ** = any depth (including slashes)
        ? = single character
        """
        import re

        parts: list[str] = []
        i = 0
        while i < len(pattern):
            c = pattern[i]
            if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
                parts.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1  # skip trailing slash after **
                continue
            elif c == "*":
                parts.append("[^/]*")
                i += 1
                continue
            elif c == "?":
                parts.append("[^/]")
                i += 1
                continue
            else:
                parts.append(re.escape(c))
                i += 1
        return "^" + "".join(parts) + "$"

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200
    ) -> list[str]:
        """Match file keys by glob pattern. Returns list of matching keys."""
        regex = self._glob_to_regex(pattern)
        if prefix:
            response = self._execute(
                """SELECT f.key FROM cogos_file f
                   WHERE f.key ~ :regex
                     AND f.key LIKE :prefix
                   ORDER BY f.key
                   LIMIT :limit""",
                [
                    self._param("regex", regex),
                    self._param("prefix", prefix + "%"),
                    self._param("limit", limit),
                ],
            )
        else:
            response = self._execute(
                """SELECT f.key FROM cogos_file f
                   WHERE f.key ~ :regex
                   ORDER BY f.key
                   LIMIT :limit""",
                [
                    self._param("regex", regex),
                    self._param("limit", limit),
                ],
            )
        return [r["key"] for r in self._rows_to_dicts(response)]

    # ═══════════════════════════════════════════════════════════
    # FILE VERSIONS
    # ═══════════════════════════════════════════════════════════

    def insert_file_version(self, fv: FileVersion) -> None:
        self._execute(
            """INSERT INTO cogos_file_version (id, file_id, version, read_only, content, source, is_active, run_id)
               VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active, :run_id)
               ON CONFLICT (file_id, version) DO UPDATE SET
                   content = EXCLUDED.content,
                   source = EXCLUDED.source,
                   is_active = EXCLUDED.is_active,
                   run_id = COALESCE(EXCLUDED.run_id, cogos_file_version.run_id)""",
            [
                self._param("id", fv.id),
                self._param("file_id", fv.file_id),
                self._param("version", fv.version),
                self._param("read_only", fv.read_only),
                self._param("content", fv.content),
                self._param("source", fv.source),
                self._param("is_active", fv.is_active),
                self._param("run_id", fv.run_id),
            ],
        )
        self._execute(
            "UPDATE cogos_file SET updated_at = now() WHERE id = :id",
            [self._param("id", fv.file_id)],
        )

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None:
        response = self._execute(
            """SELECT * FROM cogos_file_version
               WHERE file_id = :file_id AND is_active = TRUE
               ORDER BY version DESC LIMIT 1""",
            [self._param("file_id", file_id)],
        )
        row = self._first_row(response)
        return self._file_version_from_row(row) if row else None

    def get_max_file_version(self, file_id: UUID) -> int:
        response = self._execute(
            "SELECT COALESCE(MAX(version), 0) AS max_v FROM cogos_file_version WHERE file_id = :file_id",
            [self._param("file_id", file_id)],
        )
        row = self._first_row(response)
        return row["max_v"] if row else 0

    def list_file_versions(self, file_id: UUID) -> list[FileVersion]:
        response = self._execute(
            "SELECT * FROM cogos_file_version WHERE file_id = :file_id ORDER BY version",
            [self._param("file_id", file_id)],
        )
        return [self._file_version_from_row(r) for r in self._rows_to_dicts(response)]

    def set_active_file_version(self, file_id: UUID, version: int) -> None:
        self._execute(
            "UPDATE cogos_file_version SET is_active = FALSE WHERE file_id = :file_id",
            [self._param("file_id", file_id)],
        )
        self._execute(
            "UPDATE cogos_file_version SET is_active = TRUE WHERE file_id = :file_id AND version = :version",
            [self._param("file_id", file_id), self._param("version", version)],
        )

    def _file_version_from_row(self, row: dict) -> FileVersion:
        return FileVersion(
            id=UUID(row["id"]),
            file_id=UUID(row["file_id"]),
            version=row["version"],
            read_only=row.get("read_only", False),
            content=row.get("content", ""),
            source=row.get("source", "cogent"),
            is_active=row.get("is_active", True),
            run_id=UUID(row["run_id"]) if row.get("run_id") else None,
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # CAPABILITIES
    # ═══════════════════════════════════════════════════════════

    def upsert_capability(self, cap: Capability) -> UUID:
        cap.schema = self._jsonb_safe(cap.schema)
        cap.metadata = self._jsonb_safe(cap.metadata) or {}
        response = self._execute(
            """INSERT INTO cogos_capability
                   (id, name, description, instructions, handler,
                    schema, iam_role_arn, enabled, metadata)
               VALUES (:id, :name, :description, :instructions, :handler,
                       :schema::jsonb,
                       :iam_role_arn, :enabled, :metadata::jsonb)
               ON CONFLICT (name) DO UPDATE SET
                   description = EXCLUDED.description,
                   instructions = EXCLUDED.instructions,
                   handler = EXCLUDED.handler,
                   schema = EXCLUDED.schema,
                   iam_role_arn = EXCLUDED.iam_role_arn,
                   enabled = EXCLUDED.enabled,
                   metadata = EXCLUDED.metadata,
                   updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", cap.id),
                self._param("name", cap.name),
                self._param("description", cap.description),
                self._param("instructions", cap.instructions),
                self._param("handler", cap.handler),
                self._param("schema", cap.schema),
                self._param("iam_role_arn", cap.iam_role_arn),
                self._param("enabled", cap.enabled),
                self._param("metadata", cap.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            cap.created_at = self._ts(row, "created_at")
            cap.updated_at = self._ts(row, "updated_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert capability")

    def get_capability(self, cap_id: UUID) -> Capability | None:
        response = self._execute(
            "SELECT * FROM cogos_capability WHERE id = :id",
            [self._param("id", cap_id)],
        )
        row = self._first_row(response)
        return self._capability_from_row(row) if row else None

    def get_capability_by_name(self, name: str) -> Capability | None:
        response = self._execute(
            "SELECT * FROM cogos_capability WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._capability_from_row(row) if row else None

    def get_capability_by_handler(self, handler: str) -> Capability | None:
        response = self._execute(
            "SELECT * FROM cogos_capability WHERE handler = :handler",
            [self._param("handler", handler)],
        )
        row = self._first_row(response)
        return self._capability_from_row(row) if row else None

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]:
        where = "WHERE enabled = TRUE" if enabled_only else ""
        response = self._execute(
            f"SELECT * FROM cogos_capability {where} ORDER BY name",
        )
        return [self._capability_from_row(r) for r in self._rows_to_dicts(response)]

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]:
        """Search capabilities by name/description matching. Optionally scoped to a process."""
        pattern = f"%{query}%"
        if process_id:
            response = self._execute(
                """SELECT c.* FROM cogos_capability c
                   JOIN cogos_process_capability pc ON pc.capability = c.id
                   WHERE pc.process = :process AND c.enabled = TRUE
                     AND (c.name ILIKE :pattern OR c.description ILIKE :pattern)
                   ORDER BY c.name""",
                [self._param("process", process_id), self._param("pattern", pattern)],
            )
        else:
            response = self._execute(
                """SELECT * FROM cogos_capability
                   WHERE enabled = TRUE
                     AND (name ILIKE :pattern OR description ILIKE :pattern)
                   ORDER BY name""",
                [self._param("pattern", pattern)],
            )
        return [self._capability_from_row(r) for r in self._rows_to_dicts(response)]

    def _capability_from_row(self, row: dict) -> Capability:
        return Capability(
            id=UUID(row["id"]),
            name=row["name"],
            description=row.get("description", ""),
            instructions=row.get("instructions", ""),
            handler=row.get("handler", ""),
            schema=self._json_field(row, "schema", {}),
            iam_role_arn=row.get("iam_role_arn"),
            enabled=row.get("enabled", True),
            metadata=self._json_field(row, "metadata", {}),
            created_at=self._ts(row, "created_at"),
            updated_at=self._ts(row, "updated_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════

    def upsert_resource(self, resource: Resource) -> str:
        """Insert or update a resource by name."""
        resource.metadata = self._jsonb_safe(resource.metadata) or {}
        response = self._execute(
            """INSERT INTO resources (name, resource_type, capacity, metadata)
               VALUES (:name, :resource_type, :capacity, :metadata::jsonb)
               ON CONFLICT (name)
               DO UPDATE SET resource_type = EXCLUDED.resource_type,
                            capacity = EXCLUDED.capacity,
                            metadata = EXCLUDED.metadata
               RETURNING name, created_at""",
            [
                self._param("name", resource.name),
                self._param("resource_type", resource.resource_type.value),
                self._param("capacity", resource.capacity),
                self._param("metadata", resource.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            resource.created_at = self._ts(row, "created_at")
            return row["name"]
        raise RuntimeError("Failed to upsert resource")

    def list_resources(self) -> list[Resource]:
        response = self._execute("SELECT * FROM resources ORDER BY name")
        return [self._resource_from_row(r) for r in self._rows_to_dicts(response)]

    def _resource_from_row(self, row: dict) -> Resource:
        return Resource(
            name=row["name"],
            resource_type=ResourceType(row["resource_type"]),
            capacity=float(row.get("capacity", 1.0)),
            metadata=self._json_field(row, "metadata", {}),
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # RUNS
    # ═══════════════════════════════════════════════════════════

    def create_run(self, run: Run) -> UUID:
        if not run.epoch:
            run.epoch = self.reboot_epoch
        run.result = self._jsonb_safe(run.result)
        run.snapshot = self._jsonb_safe(run.snapshot)
        run.scope_log = self._jsonb_safe(run.scope_log) or []
        response = self._execute(
            """INSERT INTO cogos_run
                   (id, process, message, conversation, status,
                    tokens_in, tokens_out, cost_usd, duration_ms,
                    error, model_version, result, snapshot, scope_log,
                    trace_id, parent_trace_id, epoch)
               VALUES (:id, :process, :message, :conversation, :status,
                       :tokens_in, :tokens_out, :cost_usd::numeric, :duration_ms,
                       :error, :model_version, :result::jsonb, :snapshot::jsonb, :scope_log::jsonb,
                       :trace_id, :parent_trace_id, :epoch)
               RETURNING id, created_at""",
            [
                self._param("id", run.id),
                self._param("process", run.process),
                self._param("message", run.message),
                self._param("conversation", run.conversation),
                self._param("status", run.status.value),
                self._param("tokens_in", run.tokens_in),
                self._param("tokens_out", run.tokens_out),
                self._param("cost_usd", run.cost_usd),
                self._param("duration_ms", run.duration_ms),
                self._param("error", run.error),
                self._param("model_version", run.model_version),
                self._param("result", run.result),
                self._param("snapshot", run.snapshot),
                self._param("scope_log", run.scope_log),
                self._param("trace_id", run.trace_id),
                self._param("parent_trace_id", run.parent_trace_id),
                self._param("epoch", run.epoch),
            ],
        )
        row = self._first_row(response)
        if row:
            run.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to create run")

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
        result = self._jsonb_safe(result)
        snapshot = self._jsonb_safe(snapshot)
        scope_log = self._jsonb_safe(scope_log)
        response = self._execute(
            """UPDATE cogos_run SET
                   status = :status, tokens_in = :tokens_in, tokens_out = :tokens_out,
                   cost_usd = :cost_usd::numeric, duration_ms = :duration_ms,
                   error = :error,
                   model_version = COALESCE(:model_version, model_version),
                   result = :result::jsonb,
                   snapshot = COALESCE(:snapshot::jsonb, snapshot),
                   scope_log = COALESCE(:scope_log::jsonb, scope_log),
                   completed_at = now()
               WHERE id = :id""",
            [
                self._param("id", run_id),
                self._param("status", status.value),
                self._param("tokens_in", tokens_in),
                self._param("tokens_out", tokens_out),
                self._param("cost_usd", cost_usd),
                self._param("duration_ms", duration_ms),
                self._param("error", error),
                self._param("model_version", model_version),
                self._param("result", result),
                self._param("snapshot", snapshot),
                self._param("scope_log", scope_log),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int:
        """Mark RUNNING runs older than max_age_ms as TIMEOUT. Returns count updated."""
        response = self._execute(
            """UPDATE cogos_run SET
                   status = 'timeout',
                   error = 'Run exceeded maximum duration and was reaped by dispatcher',
                   completed_at = now()
               WHERE status = 'running'
                 AND created_at < now() - make_interval(secs => :max_age_s)
               """,
            [self._param("max_age_s", max_age_ms / 1000.0)],
        )
        return response.get("numberOfRecordsUpdated", 0)

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        """List runs that failed or timed out within the last max_age_ms."""
        response = self._execute(
            """SELECT * FROM cogos_run
               WHERE status IN ('failed', 'timeout', 'throttled')
                 AND epoch = :epoch
                 AND COALESCE(completed_at, created_at) > now() - make_interval(secs => :max_age_s)
               ORDER BY completed_at DESC""",
            [self._param("epoch", self.reboot_epoch), self._param("max_age_s", max_age_ms / 1000.0)],
        )
        return [self._run_from_row(r) for r in self._rows_to_dicts(response)]

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None:
        """Update the metadata JSON field on a run."""
        self._execute(
            "UPDATE cogos_run SET metadata = :metadata::jsonb WHERE id = :id",
            [
                self._param("id", run_id),
                self._param("metadata", self._jsonb_safe(metadata) or {}),
            ],
        )

    def get_run(self, run_id: UUID) -> Run | None:
        response = self._execute(
            "SELECT * FROM cogos_run WHERE id = :id",
            [self._param("id", run_id)],
        )
        row = self._first_row(response)
        return self._run_from_row(row) if row else None

    _RUN_SLIM_COLUMNS = (
        "id, epoch, process, message, conversation, status, tokens_in, tokens_out, "
        "cost_usd, duration_ms, error, model_version, result, trace_id, parent_trace_id, "
        "metadata, created_at, completed_at"
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
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions = []
        params = [self._param("limit", limit)]
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params.append(self._param("epoch", effective_epoch))
        if process_id:
            conditions.append("process = :process")
            params.append(self._param("process", process_id))
        if process_ids:
            placeholders = ", ".join(f":pid_{i}" for i in range(len(process_ids)))
            conditions.append(f"process IN ({placeholders})")
            for i, pid in enumerate(process_ids):
                params.append(self._param(f"pid_{i}", pid))
        if status:
            conditions.append("status = :status")
            params.append(self._param("status", status))
        if since:
            conditions.append("created_at >= :since::timestamptz")
            params.append(self._param("since", since))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        columns = self._RUN_SLIM_COLUMNS if slim else "*"
        response = self._execute(
            f"SELECT {columns} FROM cogos_run{where} ORDER BY created_at DESC LIMIT :limit",
            params,
        )
        return [self._run_from_row(r) for r in self._rows_to_dicts(response)]

    def list_file_mutations(self, run_id: UUID) -> list[dict]:
        """List file versions created by a specific run."""
        response = self._execute(
            """SELECT f.key, fv.version, fv.created_at
               FROM cogos_file_version fv
               JOIN cogos_file f ON f.id = fv.file_id
               WHERE fv.run_id = :run_id
               ORDER BY fv.created_at""",
            [self._param("run_id", run_id)],
        )
        return self._rows_to_dicts(response)

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        """List runs for processes whose name matches a glob pattern."""
        like_pattern = name_pattern.replace("*", "%").replace("?", "_")
        conditions = ["p.name LIKE :name_pattern", "r.epoch = :epoch"]
        params = [
            self._param("name_pattern", like_pattern),
            self._param("epoch", self.reboot_epoch),
            self._param("limit", limit),
        ]
        if status:
            conditions.append("r.status = :status")
            params.append(self._param("status", status))
        if since:
            conditions.append("r.created_at >= :since::timestamptz")
            params.append(self._param("since", since))
        where = " AND ".join(conditions)
        response = self._execute(
            f"""SELECT r.* FROM cogos_run r
                JOIN cogos_process p ON p.id = r.process
                WHERE {where}
                ORDER BY r.created_at DESC LIMIT :limit""",
            params,
        )
        return [self._run_from_row(r) for r in self._rows_to_dicts(response)]

    def _run_from_row(self, row: dict) -> Run:
        return Run(
            id=UUID(row["id"]),
            epoch=row.get("epoch", 0),
            process=UUID(row["process"]),
            message=UUID(row["message"]) if row.get("message") else None,
            conversation=UUID(row["conversation"]) if row.get("conversation") else None,
            status=RunStatus(row["status"]),
            tokens_in=row.get("tokens_in", 0),
            tokens_out=row.get("tokens_out", 0),
            cost_usd=Decimal(str(row.get("cost_usd", 0))),
            duration_ms=row.get("duration_ms"),
            error=row.get("error"),
            model_version=row.get("model_version"),
            result=self._json_field(row, "result"),
            snapshot=self._json_field(row, "snapshot"),
            scope_log=self._json_field(row, "scope_log", []),
            trace_id=UUID(row["trace_id"]) if row.get("trace_id") else None,
            parent_trace_id=UUID(row["parent_trace_id"]) if row.get("parent_trace_id") else None,
            metadata=self._json_field(row, "metadata"),
            created_at=self._ts(row, "created_at"),
            completed_at=self._ts(row, "completed_at"),
        )

    def _delivery_from_row(self, row: dict) -> Delivery:
        return Delivery(
            id=UUID(row["id"]),
            epoch=row.get("epoch", 0),
            message=UUID(row["message"]),
            handler=UUID(row["handler"]),
            status=DeliveryStatus(row["status"]),
            run=UUID(row["run"]) if row.get("run") else None,
            trace_id=UUID(row["trace_id"]) if row.get("trace_id") else None,
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # TRACES
    # ═══════════════════════════════════════════════════════════

    def create_trace(self, trace: Trace) -> UUID:
        trace.capability_calls = self._jsonb_safe(trace.capability_calls) or []
        trace.file_ops = self._jsonb_safe(trace.file_ops) or []
        response = self._execute(
            """INSERT INTO cogos_trace (id, run, capability_calls, file_ops, model_version)
               VALUES (:id, :run, :capability_calls::jsonb, :file_ops::jsonb, :model_version)
               RETURNING id, created_at""",
            [
                self._param("id", trace.id),
                self._param("run", trace.run),
                self._param("capability_calls", trace.capability_calls),
                self._param("file_ops", trace.file_ops),
                self._param("model_version", trace.model_version),
            ],
        )
        row = self._first_row(response)
        if row:
            trace.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        return trace.id

    # ═══════════════════════════════════════════════════════════
    # REQUEST TRACES & SPANS
    # ═══════════════════════════════════════════════════════════

    def create_request_trace(self, trace: RequestTrace) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_request_trace (id, cogent_id, source, source_ref)
               VALUES (:id, :cogent_id, :source, :source_ref)
               RETURNING id, created_at""",
            [
                self._param("id", trace.id),
                self._param("cogent_id", trace.cogent_id),
                self._param("source", trace.source),
                self._param("source_ref", trace.source_ref),
            ],
        )
        row = self._first_row(response)
        if row:
            trace.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to create request trace")

    def get_request_trace(self, trace_id: UUID) -> RequestTrace | None:
        response = self._execute(
            "SELECT * FROM cogos_request_trace WHERE id = :id",
            [self._param("id", trace_id)],
        )
        row = self._first_row(response)
        if not row:
            return None
        return RequestTrace(
            id=UUID(row["id"]),
            cogent_id=row.get("cogent_id", ""),
            source=row.get("source", ""),
            source_ref=row.get("source_ref"),
            created_at=self._ts(row, "created_at"),
        )

    def create_span(self, span: Span) -> UUID:
        span.metadata = self._jsonb_safe(span.metadata) or {}
        response = self._execute(
            """INSERT INTO cogos_span
                   (id, trace_id, parent_span_id, name, coglet, status, metadata)
               VALUES (:id, :trace_id, :parent_span_id, :name, :coglet, :status, :metadata::jsonb)
               RETURNING id, started_at""",
            [
                self._param("id", span.id),
                self._param("trace_id", span.trace_id),
                self._param("parent_span_id", span.parent_span_id),
                self._param("name", span.name),
                self._param("coglet", span.coglet),
                self._param("status", span.status.value),
                self._param("metadata", span.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            span.started_at = self._ts(row, "started_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to create span")

    def complete_span(self, span_id: UUID, *, status: str = "completed", metadata: dict | None = None) -> bool:
        metadata = self._jsonb_safe(metadata)
        if metadata:
            response = self._execute(
                """UPDATE cogos_span SET status = :status, ended_at = now(),
                       metadata = metadata || :metadata::jsonb
                   WHERE id = :id""",
                [
                    self._param("id", span_id),
                    self._param("status", status),
                    self._param("metadata", metadata),
                ],
            )
        else:
            response = self._execute(
                "UPDATE cogos_span SET status = :status, ended_at = now() WHERE id = :id",
                [self._param("id", span_id), self._param("status", status)],
            )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def list_spans(self, trace_id: UUID) -> list[Span]:
        response = self._execute(
            "SELECT * FROM cogos_span WHERE trace_id = :trace_id ORDER BY started_at",
            [self._param("trace_id", trace_id)],
        )
        return [self._span_from_row(r) for r in self._rows_to_dicts(response)]

    def create_span_event(self, event: SpanEvent) -> UUID:
        event.metadata = self._jsonb_safe(event.metadata) or {}
        response = self._execute(
            """INSERT INTO cogos_span_event (id, span_id, event, message, metadata)
               VALUES (:id, :span_id, :event, :message, :metadata::jsonb)
               RETURNING id, timestamp""",
            [
                self._param("id", event.id),
                self._param("span_id", event.span_id),
                self._param("event", event.event),
                self._param("message", event.message),
                self._param("metadata", event.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            event.timestamp = self._ts(row, "timestamp")
            return UUID(row["id"])
        raise RuntimeError("Failed to create span event")

    def list_span_events(self, span_id: UUID) -> list[SpanEvent]:
        response = self._execute(
            "SELECT * FROM cogos_span_event WHERE span_id = :span_id ORDER BY timestamp",
            [self._param("span_id", span_id)],
        )
        return [self._span_event_from_row(r) for r in self._rows_to_dicts(response)]

    def list_span_events_for_trace(self, trace_id: UUID) -> list[SpanEvent]:
        response = self._execute(
            """SELECT e.* FROM cogos_span_event e
               JOIN cogos_span s ON s.id = e.span_id
               WHERE s.trace_id = :trace_id
               ORDER BY e.timestamp""",
            [self._param("trace_id", trace_id)],
        )
        return [self._span_event_from_row(r) for r in self._rows_to_dicts(response)]

    def _span_from_row(self, row: dict) -> Span:
        return Span(
            id=UUID(row["id"]),
            trace_id=UUID(row["trace_id"]),
            parent_span_id=UUID(row["parent_span_id"]) if row.get("parent_span_id") else None,
            name=row["name"],
            coglet=row.get("coglet"),
            status=SpanStatus(row["status"]),
            started_at=self._ts(row, "started_at"),
            ended_at=self._ts(row, "ended_at"),
            metadata=self._json_field(row, "metadata", {}),
        )

    def _span_event_from_row(self, row: dict) -> SpanEvent:
        return SpanEvent(
            id=UUID(row["id"]),
            span_id=UUID(row["span_id"]),
            event=row["event"],
            message=row.get("message"),
            timestamp=self._ts(row, "timestamp"),
            metadata=self._json_field(row, "metadata", {}),
        )

    # ═══════════════════════════════════════════════════════════
    # META (key-value)
    # ═══════════════════════════════════════════════════════════

    def set_meta(self, key: str, value: str = "") -> None:
        self._execute(
            """INSERT INTO cogos_meta (key, value, updated_at)
               VALUES (:key, :value, now())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            [self._param("key", key), self._param("value", value)],
        )

    def get_meta(self, key: str) -> dict[str, str] | None:
        row = self._first_row(self._execute(
            "SELECT key, value, updated_at FROM cogos_meta WHERE key = :key",
            [self._param("key", key)],
        ))
        if not row:
            return None
        return {
            "key": row["key"],
            "value": row.get("value", ""),
            "updated_at": str(self._ts(row, "updated_at")) if self._ts(row, "updated_at") else "",
        }

    def create_alert(self, severity: str, alert_type: str, source: str, message: str, metadata: dict | None = None) -> None:
        """Insert into the shared alerts table (algedonic channel)."""
        from uuid import uuid4
        self._execute(
            """INSERT INTO alerts (id, severity, alert_type, source, message, metadata)
               VALUES (:id, :severity, :alert_type, :source, :message, :metadata::jsonb)""",
            [
                self._param("id", uuid4()),
                self._param("severity", severity),
                self._param("alert_type", alert_type),
                self._param("source", source),
                self._param("message", message),
                self._param("metadata", self._jsonb_safe(metadata) or {}),
            ],
        )

    def list_alerts(self, *, resolved: bool = False, limit: int = 50) -> list[dict]:
        """Return recent alerts, unresolved by default."""
        where = "" if resolved else "WHERE resolved_at IS NULL"
        response = self._execute(
            f"SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT :limit",
            [self._param("limit", limit)],
        )
        return self._rows_to_dicts(response)

    def resolve_alert(self, alert_id) -> None:
        self._execute(
            "UPDATE alerts SET resolved_at = now() WHERE id = :id",
            [self._param("id", alert_id)],
        )

    # ═══════════════════════════════════════════════════════════
    # SCHEMAS
    # ═══════════════════════════════════════════════════════════

    def upsert_schema(self, s: Schema) -> UUID:
        s.definition = self._jsonb_safe(s.definition) or {}
        response = self._execute(
            """INSERT INTO cogos_schema (id, name, definition, file_id)
               VALUES (:id, :name, :definition::jsonb, :file_id)
               ON CONFLICT (name) DO UPDATE SET
                   definition = EXCLUDED.definition,
                   file_id = EXCLUDED.file_id
               RETURNING id, created_at""",
            [
                self._param("id", s.id),
                self._param("name", s.name),
                self._param("definition", s.definition),
                self._param("file_id", s.file_id),
            ],
        )
        row = self._first_row(response)
        if row:
            s.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert schema")

    def get_schema(self, schema_id: UUID) -> Schema | None:
        response = self._execute(
            "SELECT * FROM cogos_schema WHERE id = :id",
            [self._param("id", schema_id)],
        )
        row = self._first_row(response)
        return self._schema_from_row(row) if row else None

    def get_schema_by_name(self, name: str) -> Schema | None:
        response = self._execute(
            "SELECT * FROM cogos_schema WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._schema_from_row(row) if row else None

    def list_schemas(self) -> list[Schema]:
        response = self._execute("SELECT * FROM cogos_schema ORDER BY name")
        return [self._schema_from_row(r) for r in self._rows_to_dicts(response)]

    def _schema_from_row(self, row: dict) -> Schema:
        return Schema(
            id=UUID(row["id"]),
            name=row["name"],
            definition=self._json_field(row, "definition", {}),
            file_id=UUID(row["file_id"]) if row.get("file_id") else None,
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # CHANNELS
    # ═══════════════════════════════════════════════════════════

    def upsert_channel(self, ch: Channel) -> UUID:
        ch.inline_schema = self._jsonb_safe(ch.inline_schema)
        response = self._execute(
            """INSERT INTO cogos_channel
                   (id, name, owner_process, schema_id, inline_schema,
                    channel_type, auto_close, closed_at)
               VALUES (:id, :name, :owner_process, :schema_id, :inline_schema::jsonb,
                       :channel_type, :auto_close, :closed_at)
               ON CONFLICT (name) DO UPDATE SET
                   owner_process = EXCLUDED.owner_process,
                   schema_id = EXCLUDED.schema_id,
                   inline_schema = EXCLUDED.inline_schema,
                   channel_type = EXCLUDED.channel_type,
                   auto_close = EXCLUDED.auto_close,
                   closed_at = EXCLUDED.closed_at
               RETURNING id, created_at""",
            [
                self._param("id", ch.id),
                self._param("name", ch.name),
                self._param("owner_process", ch.owner_process),
                self._param("schema_id", ch.schema_id),
                self._param("inline_schema", ch.inline_schema),
                self._param("channel_type", ch.channel_type.value),
                self._param("auto_close", ch.auto_close),
                self._param("closed_at", ch.closed_at),
            ],
        )
        row = self._first_row(response)
        if row:
            ch.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert channel")

    def get_channel(self, channel_id: UUID) -> Channel | None:
        response = self._execute(
            "SELECT * FROM cogos_channel WHERE id = :id",
            [self._param("id", channel_id)],
        )
        row = self._first_row(response)
        return self._channel_from_row(row) if row else None

    def get_channel_by_name(self, name: str) -> Channel | None:
        response = self._execute(
            "SELECT * FROM cogos_channel WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._channel_from_row(row) if row else None

    def list_channels(self, *, owner_process: UUID | None = None) -> list[Channel]:
        if owner_process is not None:
            response = self._execute(
                "SELECT * FROM cogos_channel WHERE owner_process = :owner ORDER BY name",
                [self._param("owner", owner_process)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_channel ORDER BY name",
            )
        return [self._channel_from_row(r) for r in self._rows_to_dicts(response)]

    def close_channel(self, channel_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_channel SET closed_at = now() WHERE id = :id AND closed_at IS NULL",
            [self._param("id", channel_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _channel_from_row(self, row: dict) -> Channel:
        return Channel(
            id=UUID(row["id"]),
            name=row["name"],
            owner_process=UUID(row["owner_process"]) if row.get("owner_process") else None,
            schema_id=UUID(row["schema_id"]) if row.get("schema_id") else None,
            inline_schema=self._json_field(row, "inline_schema"),
            channel_type=ChannelType(row["channel_type"]),
            auto_close=row.get("auto_close", False),
            closed_at=self._ts(row, "closed_at"),
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # CHANNEL MESSAGES
    # ═══════════════════════════════════════════════════════════

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        msg.payload = self._jsonb_safe(msg.payload) or {}
        msg.trace_meta = self._jsonb_safe(msg.trace_meta)
        if msg.idempotency_key:
            response = self._execute(
                """INSERT INTO cogos_channel_message (id, channel, sender_process, payload, idempotency_key, trace_id, trace_meta)
                   VALUES (:id, :channel, :sender_process, :payload::jsonb, :idempotency_key, :trace_id, :trace_meta::jsonb)
                   ON CONFLICT (channel, idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
                   RETURNING id, created_at""",
                [
                    self._param("id", msg.id),
                    self._param("channel", msg.channel),
                    self._param("sender_process", msg.sender_process),
                    self._param("payload", msg.payload),
                    self._param("idempotency_key", msg.idempotency_key),
                    self._param("trace_id", msg.trace_id),
                    self._param("trace_meta", msg.trace_meta),
                ],
            )
            row = self._first_row(response)
            if not row:
                # Duplicate — fetch the existing message ID
                existing = self._first_row(self._execute(
                    """SELECT id, created_at FROM cogos_channel_message
                       WHERE channel = :channel AND idempotency_key = :key""",
                    [self._param("channel", msg.channel),
                     self._param("key", msg.idempotency_key)],
                ))
                if existing:
                    logger.info("Duplicate channel message (idempotency_key=%s), skipping", msg.idempotency_key)
                    return UUID(existing["id"])  # skip delivery creation for duplicates
                raise RuntimeError("Failed to append channel message")
        else:
            response = self._execute(
                """INSERT INTO cogos_channel_message (id, channel, sender_process, payload, trace_id, trace_meta)
                   VALUES (:id, :channel, :sender_process, :payload::jsonb, :trace_id, :trace_meta::jsonb)
                   RETURNING id, created_at""",
                [
                    self._param("id", msg.id),
                    self._param("channel", msg.channel),
                    self._param("sender_process", msg.sender_process),
                    self._param("payload", msg.payload),
                    self._param("trace_id", msg.trace_id),
                    self._param("trace_meta", msg.trace_meta),
                ],
            )
            row = self._first_row(response)
            if not row:
                raise RuntimeError("Failed to append channel message")

        msg.created_at = self._ts(row, "created_at")
        msg_id = UUID(row["id"])

        # Auto-create deliveries for handlers bound to this channel
        handlers = self.match_handlers_by_channel(msg.channel)
        for handler in handlers:
            delivery = Delivery(message=msg_id, handler=handler.id, trace_id=msg.trace_id)
            _delivery_id, inserted = self.create_delivery(delivery)
            if inserted:
                proc = self.get_process(handler.process)
                if proc and proc.status == ProcessStatus.WAITING:
                    self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                    self._nudge_ingress(process_id=handler.process)

        return msg_id

    def get_latest_delivery_time(self, handler_id: UUID):
        """Return the created_at of the most recent message delivered to this handler."""
        row = self._first_row(self._execute(
            """SELECT MAX(cm.created_at) AS latest
               FROM cogos_delivery d
               JOIN cogos_channel_message cm ON d.message = cm.id
               WHERE d.handler = :handler""",
            [self._param("handler", handler_id)],
        ))
        return self._ts(row, "latest") if row and row.get("latest") else None

    def list_channel_messages(
        self, channel_id: UUID | None = None, *, limit: int = 100, since=None,
    ) -> list[ChannelMessage]:
        if channel_id is not None:
            if since:
                response = self._execute(
                    """SELECT * FROM cogos_channel_message
                       WHERE channel = :channel AND created_at > :since::timestamptz
                       ORDER BY created_at ASC
                       LIMIT :limit""",
                    [self._param("channel", channel_id),
                     self._param("since", since.isoformat()),
                     self._param("limit", limit)],
                )
            else:
                response = self._execute(
                    """SELECT * FROM cogos_channel_message
                       WHERE channel = :channel
                       ORDER BY created_at ASC
                       LIMIT :limit""",
                    [self._param("channel", channel_id), self._param("limit", limit)],
                )
        else:
            response = self._execute(
                """SELECT * FROM cogos_channel_message
                   ORDER BY created_at DESC
                   LIMIT :limit""",
                [self._param("limit", limit)],
            )
        return [
            ChannelMessage(
                id=UUID(r["id"]),
                channel=UUID(r["channel"]),
                sender_process=UUID(r["sender_process"]) if r.get("sender_process") else None,
                payload=self._json_field(r, "payload", {}),
                trace_id=UUID(r["trace_id"]) if r.get("trace_id") else None,
                trace_meta=self._json_field(r, "trace_meta"),
                created_at=self._ts(r, "created_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    # ═══════════════════════════════════════════════════════════
    # DISCORD METADATA
    # ═══════════════════════════════════════════════════════════

    def upsert_discord_guild(self, guild: DiscordGuild) -> None:
        self._execute(
            """INSERT INTO cogos_discord_guild
                   (guild_id, cogent_name, name, icon_url, member_count, synced_at)
               VALUES (:guild_id, :cogent_name, :name, :icon_url, :member_count, NOW())
               ON CONFLICT (guild_id) DO UPDATE SET
                   cogent_name = EXCLUDED.cogent_name,
                   name = EXCLUDED.name,
                   icon_url = EXCLUDED.icon_url,
                   member_count = EXCLUDED.member_count,
                   synced_at = NOW()""",
            [
                self._param("guild_id", guild.guild_id),
                self._param("cogent_name", guild.cogent_name),
                self._param("name", guild.name),
                self._param("icon_url", guild.icon_url),
                self._param("member_count", guild.member_count),
            ],
        )

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
        row = self._first_row(self._execute(
            "SELECT * FROM cogos_discord_guild WHERE guild_id = :guild_id",
            [self._param("guild_id", guild_id)],
        ))
        if not row:
            return None
        return DiscordGuild(
            guild_id=row["guild_id"],
            cogent_name=row["cogent_name"],
            name=row["name"],
            icon_url=row.get("icon_url"),
            member_count=row.get("member_count"),
            synced_at=self._ts(row, "synced_at"),
        )

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
        if cogent_name:
            response = self._execute(
                "SELECT * FROM cogos_discord_guild WHERE cogent_name = :cogent_name ORDER BY name",
                [self._param("cogent_name", cogent_name)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_discord_guild ORDER BY name",
            )
        return [
            DiscordGuild(
                guild_id=r["guild_id"],
                cogent_name=r["cogent_name"],
                name=r["name"],
                icon_url=r.get("icon_url"),
                member_count=r.get("member_count"),
                synced_at=self._ts(r, "synced_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def delete_discord_guild(self, guild_id: str) -> None:
        self._execute(
            "DELETE FROM cogos_discord_channel WHERE guild_id = :guild_id",
            [self._param("guild_id", guild_id)],
        )
        self._execute(
            "DELETE FROM cogos_discord_guild WHERE guild_id = :guild_id",
            [self._param("guild_id", guild_id)],
        )

    def upsert_discord_channel(self, channel: DiscordChannel) -> None:
        self._execute(
            """INSERT INTO cogos_discord_channel
                   (channel_id, guild_id, name, topic, category, channel_type, position, synced_at)
               VALUES (:channel_id, :guild_id, :name, :topic, :category, :channel_type, :position, NOW())
               ON CONFLICT (channel_id) DO UPDATE SET
                   guild_id = EXCLUDED.guild_id,
                   name = EXCLUDED.name,
                   topic = EXCLUDED.topic,
                   category = EXCLUDED.category,
                   channel_type = EXCLUDED.channel_type,
                   position = EXCLUDED.position,
                   synced_at = NOW()""",
            [
                self._param("channel_id", channel.channel_id),
                self._param("guild_id", channel.guild_id),
                self._param("name", channel.name),
                self._param("topic", channel.topic),
                self._param("category", channel.category),
                self._param("channel_type", channel.channel_type),
                self._param("position", channel.position),
            ],
        )

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
        row = self._first_row(self._execute(
            "SELECT * FROM cogos_discord_channel WHERE channel_id = :channel_id",
            [self._param("channel_id", channel_id)],
        ))
        if not row:
            return None
        return DiscordChannel(
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            name=row["name"],
            topic=row.get("topic"),
            category=row.get("category"),
            channel_type=row["channel_type"],
            position=row.get("position", 0),
            synced_at=self._ts(row, "synced_at"),
        )

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
        if guild_id:
            response = self._execute(
                "SELECT * FROM cogos_discord_channel WHERE guild_id = :guild_id ORDER BY position",
                [self._param("guild_id", guild_id)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_discord_channel ORDER BY position",
            )
        return [
            DiscordChannel(
                channel_id=r["channel_id"],
                guild_id=r["guild_id"],
                name=r["name"],
                topic=r.get("topic"),
                category=r.get("category"),
                channel_type=r["channel_type"],
                position=r.get("position", 0),
                synced_at=self._ts(r, "synced_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def delete_discord_channel(self, channel_id: str) -> None:
        self._execute(
            "DELETE FROM cogos_discord_channel WHERE channel_id = :channel_id",
            [self._param("channel_id", channel_id)],
        )

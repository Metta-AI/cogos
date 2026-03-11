"""CogOS repository — CRUD for all CogOS tables via RDS Data API."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import boto3

from cogos.db.models import (
    Alert,
    AlertSeverity,
    Budget,
    BudgetPeriod,
    Capability,
    Conversation,
    ConversationStatus,
    Cron,
    DeliveryStatus,
    Event,
    EventDelivery,
    EventType,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessMode,
    ProcessStatus,
    Resource,
    ResourceType,
    ResourceUsage,
    Run,
    RunStatus,
    Trace,
)

logger = logging.getLogger(__name__)


class Repository:
    """Synchronous CogOS repository using RDS Data API."""

    def __init__(
        self,
        client: Any,
        resource_arn: str,
        secret_arn: str,
        database: str,
    ) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database

    @classmethod
    def create(
        cls,
        resource_arn: str | None = None,
        secret_arn: str | None = None,
        database: str | None = None,
        region: str | None = None,
    ) -> Repository:
        resource_arn = resource_arn or os.environ.get("DB_RESOURCE_ARN", "")
        secret_arn = secret_arn or os.environ.get("DB_SECRET_ARN", "")
        database = database or os.environ.get("DB_NAME", "")
        region = region or os.environ.get("AWS_REGION", "us-east-1")

        if not all([resource_arn, secret_arn, database]):
            raise ValueError(
                "Must provide resource_arn, secret_arn, and database "
                "via arguments or environment variables "
                "(DB_RESOURCE_ARN, DB_SECRET_ARN, DB_NAME)"
            )

        client = boto3.client("rds-data", region_name=region)
        return cls(client, resource_arn, secret_arn, database)

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
        return self._client.execute_statement(**kwargs)

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
        elif isinstance(value, (dict, list)):
            param["value"] = {"stringValue": json.dumps(value)}
        else:
            param["value"] = {"stringValue": str(value)}
        return param

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

    @staticmethod
    def _json_field(row: dict, key: str, default: Any = None) -> Any:
        val = row.get(key, default)
        if isinstance(val, str):
            return json.loads(val)
        return val if val is not None else default

    @staticmethod
    def _ts(row: dict, key: str) -> datetime | None:
        v = row.get(key)
        return datetime.fromisoformat(v) if v else None

    # ═══════════════════════════════════════════════════════════
    # PROCESSES
    # ═══════════════════════════════════════════════════════════

    def upsert_process(self, p: Process) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_process
                   (id, name, mode, content, code, files, priority, resources, runner,
                    status, runnable_since, parent_process, preemptible,
                    model, model_constraints, return_schema,
                    max_duration_ms, max_retries, retry_count, retry_backoff_ms,
                    clear_context, metadata, output_events)
               VALUES (:id, :name, :mode, :content, :code, :files::jsonb, :priority, :resources::jsonb, :runner,
                       :status, :runnable_since, :parent_process, :preemptible,
                       :model, :model_constraints::jsonb, :return_schema::jsonb,
                       :max_duration_ms, :max_retries, :retry_count, :retry_backoff_ms,
                       :clear_context, :metadata::jsonb, :output_events::jsonb)
               ON CONFLICT (name) DO UPDATE SET
                   mode = EXCLUDED.mode, content = EXCLUDED.content, code = EXCLUDED.code,
                   files = EXCLUDED.files,
                   resources = EXCLUDED.resources, runner = EXCLUDED.runner,
                   preemptible = EXCLUDED.preemptible, model = EXCLUDED.model,
                   model_constraints = EXCLUDED.model_constraints,
                   return_schema = EXCLUDED.return_schema,
                   max_duration_ms = EXCLUDED.max_duration_ms,
                   max_retries = EXCLUDED.max_retries,
                   retry_backoff_ms = EXCLUDED.retry_backoff_ms,
                   clear_context = EXCLUDED.clear_context,
                   metadata = EXCLUDED.metadata,
                   output_events = EXCLUDED.output_events,
                   updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", p.id),
                self._param("name", p.name),
                self._param("mode", p.mode.value),
                self._param("content", p.content),
                self._param("code", p.code),
                self._param("files", [str(f) for f in p.files]),
                self._param("priority", p.priority),
                self._param("resources", [str(r) for r in p.resources]),
                self._param("runner", p.runner),
                self._param("status", p.status.value),
                self._param("runnable_since", p.runnable_since),
                self._param("parent_process", p.parent_process),
                self._param("preemptible", p.preemptible),
                self._param("model", p.model),
                self._param("model_constraints", p.model_constraints),
                self._param("return_schema", p.return_schema),
                self._param("max_duration_ms", p.max_duration_ms),
                self._param("max_retries", p.max_retries),
                self._param("retry_count", p.retry_count),
                self._param("retry_backoff_ms", p.retry_backoff_ms),
                self._param("clear_context", p.clear_context),
                self._param("metadata", p.metadata),
                self._param("output_events", p.output_events),
            ],
        )
        row = self._first_row(response)
        if row:
            p.created_at = self._ts(row, "created_at")
            p.updated_at = self._ts(row, "updated_at")
            self.register_event_types(p.output_events, source="process")
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
        self, *, status: ProcessStatus | None = None, limit: int = 200,
    ) -> list[Process]:
        if status:
            response = self._execute(
                "SELECT * FROM cogos_process WHERE status = :status ORDER BY name LIMIT :limit",
                [self._param("status", status.value), self._param("limit", limit)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_process ORDER BY name LIMIT :limit",
                [self._param("limit", limit)],
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
        updated = response.get("numberOfRecordsUpdated", 0) == 1
        if updated and status == ProcessStatus.RUNNABLE:
            self.append_event(Event(
                event_type="process:status:runnable",
                source="system",
                payload={"process_id": str(process_id)},
            ))
        return updated

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        response = self._execute(
            """SELECT * FROM cogos_process WHERE status = 'runnable'
               ORDER BY priority DESC, runnable_since ASC NULLS LAST
               LIMIT :limit""",
            [self._param("limit", limit)],
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
        files_raw = self._json_field(row, "files", [])
        files = [UUID(f) for f in files_raw] if files_raw else []
        return Process(
            id=UUID(row["id"]),
            name=row["name"],
            mode=ProcessMode(row["mode"]),
            content=row.get("content", ""),
            code=UUID(row["code"]) if row.get("code") else None,
            files=files,
            priority=row.get("priority", 0.0),
            resources=resources,
            runner=row.get("runner", "lambda"),
            status=ProcessStatus(row["status"]),
            runnable_since=self._ts(row, "runnable_since"),
            parent_process=UUID(row["parent_process"]) if row.get("parent_process") else None,
            preemptible=row.get("preemptible", False),
            model=row.get("model"),
            model_constraints=self._json_field(row, "model_constraints", {}),
            return_schema=self._json_field(row, "return_schema"),
            max_duration_ms=row.get("max_duration_ms"),
            max_retries=row.get("max_retries", 0),
            retry_count=row.get("retry_count", 0),
            retry_backoff_ms=row.get("retry_backoff_ms"),
            clear_context=row.get("clear_context", False),
            metadata=self._json_field(row, "metadata", {}),
            output_events=self._json_field(row, "output_events", []),
            created_at=self._ts(row, "created_at"),
            updated_at=self._ts(row, "updated_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # PROCESS CAPABILITIES
    # ═══════════════════════════════════════════════════════════

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_process_capability (id, process, capability, config, delegatable)
               VALUES (:id, :process, :capability, :config::jsonb, :delegatable)
               ON CONFLICT (process, capability) DO UPDATE SET
                   config = EXCLUDED.config, delegatable = EXCLUDED.delegatable
               RETURNING id""",
            [
                self._param("id", pc.id),
                self._param("process", pc.process),
                self._param("capability", pc.capability),
                self._param("config", pc.config),
                self._param("delegatable", pc.delegatable),
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
                config=self._json_field(r, "config"),
                delegatable=r.get("delegatable", False),
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
                      pc.delegatable, pc.config
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
                "delegatable": r.get("delegatable", False),
                "config": self._json_field(r, "config"),
            }
            for r in rows
        ]

    # ═══════════════════════════════════════════════════════════
    # HANDLERS
    # ═══════════════════════════════════════════════════════════

    def create_handler(self, h: Handler) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_handler (id, process, event_pattern, enabled)
               VALUES (:id, :process, :event_pattern, :enabled)
               ON CONFLICT (process, event_pattern) DO UPDATE SET enabled = EXCLUDED.enabled
               RETURNING id, created_at""",
            [
                self._param("id", h.id),
                self._param("process", h.process),
                self._param("event_pattern", h.event_pattern),
                self._param("enabled", h.enabled),
            ],
        )
        row = self._first_row(response)
        if row:
            h.created_at = self._ts(row, "created_at")
            self.register_event_types([h.event_pattern], source="handler")
            return UUID(row["id"])
        return h.id

    def list_handlers(
        self, *, process_id: UUID | None = None, enabled_only: bool = False,
    ) -> list[Handler]:
        conditions = []
        params = []
        if process_id:
            conditions.append("process = :process")
            params.append(self._param("process", process_id))
        if enabled_only:
            conditions.append("enabled = TRUE")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        response = self._execute(
            f"SELECT * FROM cogos_handler {where} ORDER BY event_pattern",
            params or None,
        )
        return [
            Handler(
                id=UUID(r["id"]),
                process=UUID(r["process"]),
                event_pattern=r["event_pattern"],
                enabled=r["enabled"],
                created_at=self._ts(r, "created_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def delete_handler(self, handler_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cogos_handler WHERE id = :id",
            [self._param("id", handler_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def match_handlers(self, event_type: str) -> list[Handler]:
        """Find handlers whose event_pattern matches the given event_type.

        Supports glob matching: 'task:*' matches 'task:completed:foo'.
        """
        response = self._execute(
            """SELECT * FROM cogos_handler
               WHERE enabled = TRUE
                 AND :event_type LIKE REPLACE(REPLACE(event_pattern, '*', '%'), '?', '_')""",
            [self._param("event_type", event_type)],
        )
        return [
            Handler(
                id=UUID(r["id"]),
                process=UUID(r["process"]),
                event_pattern=r["event_pattern"],
                enabled=r["enabled"],
                created_at=self._ts(r, "created_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    # ═══════════════════════════════════════════════════════════
    # EVENTS
    # ═══════════════════════════════════════════════════════════

    def append_event(self, event: Event) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_event (id, event_type, source, payload, parent_event)
               VALUES (:id, :event_type, :source, :payload::jsonb, :parent_event)
               RETURNING id, created_at""",
            [
                self._param("id", event.id),
                self._param("event_type", event.event_type),
                self._param("source", event.source),
                self._param("payload", event.payload),
                self._param("parent_event", event.parent_event),
            ],
        )
        row = self._first_row(response)
        if row:
            event.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        raise RuntimeError("Failed to insert event")

    def get_events(
        self, *, event_type: str | None = None, limit: int = 100,
    ) -> list[Event]:
        if event_type:
            response = self._execute(
                """SELECT * FROM cogos_event WHERE event_type = :event_type
                   ORDER BY created_at DESC LIMIT :limit""",
                [self._param("event_type", event_type), self._param("limit", limit)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_event ORDER BY created_at DESC LIMIT :limit",
                [self._param("limit", limit)],
            )
        return [self._event_from_row(r) for r in self._rows_to_dicts(response)]

    def _event_from_row(self, row: dict) -> Event:
        return Event(
            id=UUID(row["id"]),
            event_type=row["event_type"],
            source=row.get("source"),
            payload=self._json_field(row, "payload", {}),
            parent_event=UUID(row["parent_event"]) if row.get("parent_event") else None,
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # EVENT DELIVERY
    # ═══════════════════════════════════════════════════════════

    def create_event_delivery(self, ed: EventDelivery) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_event_delivery (id, event, handler, status, run)
               VALUES (:id, :event, :handler, :status, :run)
               RETURNING id, created_at""",
            [
                self._param("id", ed.id),
                self._param("event", ed.event),
                self._param("handler", ed.handler),
                self._param("status", ed.status.value),
                self._param("run", ed.run),
            ],
        )
        row = self._first_row(response)
        if row:
            ed.created_at = self._ts(row, "created_at")
            return UUID(row["id"])
        return ed.id

    def get_pending_deliveries(self, process_id: UUID) -> list[EventDelivery]:
        response = self._execute(
            """SELECT ed.* FROM cogos_event_delivery ed
               JOIN cogos_handler h ON h.id = ed.handler
               WHERE h.process = :process AND ed.status = 'pending'
               ORDER BY ed.created_at ASC""",
            [self._param("process", process_id)],
        )
        return [
            EventDelivery(
                id=UUID(r["id"]),
                event=UUID(r["event"]),
                handler=UUID(r["handler"]),
                status=DeliveryStatus(r["status"]),
                run=UUID(r["run"]) if r.get("run") else None,
                created_at=self._ts(r, "created_at"),
            )
            for r in self._rows_to_dicts(response)
        ]

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        response = self._execute(
            "UPDATE cogos_event_delivery SET status = 'delivered', run = :run WHERE id = :id",
            [self._param("id", delivery_id), self._param("run", run_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    # ═══════════════════════════════════════════════════════════
    # CRON RULES
    # ═══════════════════════════════════════════════════════════

    def upsert_cron(self, c: Cron) -> UUID:
        # Check for existing rule with same expression + event pattern
        existing = self._first_row(self._execute(
            "SELECT id FROM cron WHERE cron_expression = :expr AND event_pattern = :evt",
            [self._param("expr", c.expression), self._param("evt", c.event_type)],
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
            """INSERT INTO cron (id, cron_expression, event_pattern, metadata, enabled)
               VALUES (:id, :expression, :event_type, :payload::jsonb, :enabled)
               RETURNING id, created_at""",
            [
                self._param("id", c.id),
                self._param("expression", c.expression),
                self._param("event_type", c.event_type),
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
                event_type=r["event_pattern"],
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

    # ═══════════════════════════════════════════════════════════
    # FILE VERSIONS
    # ═══════════════════════════════════════════════════════════

    def insert_file_version(self, fv: FileVersion) -> None:
        self._execute(
            """INSERT INTO cogos_file_version (id, file_id, version, read_only, content, source, is_active)
               VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active)""",
            [
                self._param("id", fv.id),
                self._param("file_id", fv.file_id),
                self._param("version", fv.version),
                self._param("read_only", fv.read_only),
                self._param("content", fv.content),
                self._param("source", fv.source),
                self._param("is_active", fv.is_active),
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
            created_at=self._ts(row, "created_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # CAPABILITIES
    # ═══════════════════════════════════════════════════════════

    def upsert_capability(self, cap: Capability) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_capability
                   (id, name, description, instructions, handler,
                    input_schema, output_schema, iam_role_arn, enabled, metadata, event_types)
               VALUES (:id, :name, :description, :instructions, :handler,
                       :input_schema::jsonb, :output_schema::jsonb,
                       :iam_role_arn, :enabled, :metadata::jsonb, :event_types::jsonb)
               ON CONFLICT (name) DO UPDATE SET
                   description = EXCLUDED.description,
                   instructions = EXCLUDED.instructions,
                   handler = EXCLUDED.handler,
                   input_schema = EXCLUDED.input_schema,
                   output_schema = EXCLUDED.output_schema,
                   iam_role_arn = EXCLUDED.iam_role_arn,
                   enabled = EXCLUDED.enabled,
                   metadata = EXCLUDED.metadata,
                   event_types = EXCLUDED.event_types,
                   updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", cap.id),
                self._param("name", cap.name),
                self._param("description", cap.description),
                self._param("instructions", cap.instructions),
                self._param("handler", cap.handler),
                self._param("input_schema", cap.input_schema),
                self._param("output_schema", cap.output_schema),
                self._param("iam_role_arn", cap.iam_role_arn),
                self._param("enabled", cap.enabled),
                self._param("metadata", cap.metadata),
                self._param("event_types", cap.event_types),
            ],
        )
        row = self._first_row(response)
        if row:
            cap.created_at = self._ts(row, "created_at")
            cap.updated_at = self._ts(row, "updated_at")
            self.register_event_types(cap.event_types, source="capability")
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
            input_schema=self._json_field(row, "input_schema", {}),
            output_schema=self._json_field(row, "output_schema", {}),
            iam_role_arn=row.get("iam_role_arn"),
            enabled=row.get("enabled", True),
            metadata=self._json_field(row, "metadata", {}),
            event_types=self._json_field(row, "event_types", []),
            created_at=self._ts(row, "created_at"),
            updated_at=self._ts(row, "updated_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # RUNS
    # ═══════════════════════════════════════════════════════════

    def create_run(self, run: Run) -> UUID:
        response = self._execute(
            """INSERT INTO cogos_run
                   (id, process, event, conversation, status,
                    tokens_in, tokens_out, cost_usd, duration_ms,
                    error, model_version, result, snapshot, scope_log)
               VALUES (:id, :process, :event, :conversation, :status,
                       :tokens_in, :tokens_out, :cost_usd::numeric, :duration_ms,
                       :error, :model_version, :result::jsonb, :snapshot::jsonb, :scope_log::jsonb)
               RETURNING id, created_at""",
            [
                self._param("id", run.id),
                self._param("process", run.process),
                self._param("event", run.event),
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
        result: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool:
        response = self._execute(
            """UPDATE cogos_run SET
                   status = :status, tokens_in = :tokens_in, tokens_out = :tokens_out,
                   cost_usd = :cost_usd::numeric, duration_ms = :duration_ms,
                   error = :error, result = :result::jsonb,
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
                self._param("result", result),
                self._param("scope_log", scope_log),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def get_run(self, run_id: UUID) -> Run | None:
        response = self._execute(
            "SELECT * FROM cogos_run WHERE id = :id",
            [self._param("id", run_id)],
        )
        row = self._first_row(response)
        return self._run_from_row(row) if row else None

    def list_runs(
        self, *, process_id: UUID | None = None, limit: int = 50,
    ) -> list[Run]:
        if process_id:
            response = self._execute(
                "SELECT * FROM cogos_run WHERE process = :process ORDER BY created_at DESC LIMIT :limit",
                [self._param("process", process_id), self._param("limit", limit)],
            )
        else:
            response = self._execute(
                "SELECT * FROM cogos_run ORDER BY created_at DESC LIMIT :limit",
                [self._param("limit", limit)],
            )
        return [self._run_from_row(r) for r in self._rows_to_dicts(response)]

    def _run_from_row(self, row: dict) -> Run:
        return Run(
            id=UUID(row["id"]),
            process=UUID(row["process"]),
            event=UUID(row["event"]) if row.get("event") else None,
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
            created_at=self._ts(row, "created_at"),
            completed_at=self._ts(row, "completed_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # TRACES
    # ═══════════════════════════════════════════════════════════

    def create_trace(self, trace: Trace) -> UUID:
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

    # ═══════════════════════════════════════════════════════════
    # EVENT TYPES
    # ═══════════════════════════════════════════════════════════

    def list_event_types(self) -> list[EventType]:
        """List all registered event types."""
        rows = self._rows_to_dicts(self._execute("SELECT * FROM cogos_event_type ORDER BY name"))
        return [
            EventType(
                name=r["name"],
                description=r.get("description", ""),
                source=r.get("source", ""),
                created_at=self._ts(r, "created_at"),
            )
            for r in rows
        ]

    def upsert_event_type(self, et: EventType) -> None:
        """Insert or update an event type."""
        self._execute(
            """INSERT INTO cogos_event_type (name, description, source)
               VALUES (:name, :desc, :source)
               ON CONFLICT (name) DO UPDATE SET
                   description = CASE WHEN cogos_event_type.description = '' THEN EXCLUDED.description ELSE cogos_event_type.description END""",
            [self._param("name", et.name), self._param("desc", et.description), self._param("source", et.source)],
        )

    def register_event_types(self, names: list[str], source: str = "", description: str = "") -> None:
        """Bulk-register event type names (skip globs with * or ?)."""
        for name in names:
            if "*" in name or "?" in name:
                continue
            self.upsert_event_type(EventType(name=name, source=source, description=description))

    def delete_event_type(self, name: str) -> bool:
        resp = self._execute(
            "DELETE FROM cogos_event_type WHERE name = :name",
            [self._param("name", name)],
        )
        return resp.get("numberOfRecordsUpdated", 0) > 0

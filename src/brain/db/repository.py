"""Synchronous PostgreSQL repository using RDS Data API: CRUD for all 12 tables."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import boto3

from brain.db.models import (
    Alert,
    AlertSeverity,
    Budget,
    BudgetPeriod,
    Channel,
    ChannelType,
    Conversation,
    ConversationStatus,
    Cron,
    Event,
    MemoryRecord,
    MemoryScope,
    Program,
    ProgramType,
    Resource,
    ResourceType,
    ResourceUsage,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Trace,
    Trigger,
    TriggerConfig,
)

logger = logging.getLogger(__name__)


class Repository:
    """Synchronous database repository using RDS Data API."""

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
        """Create repository from arguments or environment variables."""
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

        # Support cross-account access via role assumption (e.g. polis dashboard)
        role_arn = os.environ.get("AWS_ROLE_ARN", "")
        if role_arn:
            sts = boto3.client("sts", region_name=region)
            creds = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName="dashboard",
            )["Credentials"]
            session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=region,
            )
            client = session.client("rds-data", region_name=region)
        else:
            client = boto3.client("rds-data", region_name=region)
        return cls(client, resource_arn, secret_arn, database)

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
        # No cleanup needed for Data API
        pass

    # ═══════════════════════════════════════════════════════════
    # HELPER METHODS
    # ═══════════════════════════════════════════════════════════

    def _execute(self, sql: str, params: list[dict] | None = None) -> dict:
        """Execute SQL statement using RDS Data API."""
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
        """Build Data API parameter dict from Python value."""
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
        elif isinstance(value, (datetime, date)):
            param["value"] = {"stringValue": value.isoformat()}
        elif isinstance(value, (dict, list)):
            param["value"] = {"stringValue": json.dumps(value)}
        else:
            param["value"] = {"stringValue": str(value)}

        return param

    def _extract_value(self, cell: dict) -> Any:
        """Extract value from Data API cell dict."""
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
        if "blobValue" in cell:
            return cell["blobValue"]
        return None

    def _rows_to_dicts(self, response: dict) -> list[dict]:
        """Convert Data API response to list[dict] using columnMetadata."""
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
        """Return first row as dict or None."""
        rows = self._rows_to_dicts(response)
        return rows[0] if rows else None

    # ═══════════════════════════════════════════════════════════
    # RAW QUERY (for dashboard / ad-hoc SQL)
    # ═══════════════════════════════════════════════════════════

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Execute raw SQL and return rows as list[dict].

        Params use :name placeholders.  Pass a plain dict, e.g.
        ``{"cogent_id": "x", "limit": 10}``.
        """
        api_params = [self._param(k, v) for k, v in params.items()] if params else None
        return self._rows_to_dicts(self._execute(sql, api_params))

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict | None:
        """Execute raw SQL and return first row or None."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Execute a write statement and return number of affected rows."""
        api_params = [self._param(k, v) for k, v in params.items()] if params else None
        response = self._execute(sql, api_params)
        return response.get("numberOfRecordsUpdated", 0)

    # ═══════════════════════════════════════════════════════════
    # EVENTS (append-only log)
    # ═══════════════════════════════════════════════════════════

    def append_event(self, event: Event) -> int:
        response = self._execute(
            """INSERT INTO events (event_type, source, payload, parent_event_id)
               VALUES (:event_type, :source, :payload::jsonb, :parent_event_id)
               RETURNING id, created_at""",
            [
                self._param("event_type", event.event_type),
                self._param("source", event.source),
                self._param("payload", event.payload),
                self._param("parent_event_id", event.parent_event_id),
            ],
        )
        row = self._first_row(response)
        if row:
            event.id = row["id"]
            event.created_at = datetime.fromisoformat(row["created_at"])
            return row["id"]
        raise RuntimeError("Failed to insert event")

    def get_events(
        self,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        if event_type:
            response = self._execute(
                """SELECT id, event_type, source, payload, parent_event_id, created_at
                   FROM events WHERE event_type = :event_type
                   ORDER BY created_at DESC LIMIT :limit""",
                [
                    self._param("event_type", event_type),
                    self._param("limit", limit),
                ],
            )
        else:
            response = self._execute(
                """SELECT id, event_type, source, payload, parent_event_id, created_at
                   FROM events
                   ORDER BY created_at DESC LIMIT :limit""",
                [
                    self._param("limit", limit),
                ],
            )
        return [self._event_from_row(r) for r in self._rows_to_dicts(response)]

    def get_event_tree(self, event_id: int) -> list[Event]:
        """Get an event and all its descendants (full causal tree)."""
        response = self._execute(
            """WITH RECURSIVE tree AS (
                 SELECT id, event_type, source, payload, parent_event_id, created_at
                 FROM events WHERE id = :event_id
                 UNION ALL
                 SELECT e.id, e.event_type, e.source, e.payload, e.parent_event_id, e.created_at
                 FROM events e JOIN tree t ON e.parent_event_id = t.id
               )
               SELECT * FROM tree ORDER BY created_at""",
            [self._param("event_id", event_id)],
        )
        return [self._event_from_row(r) for r in self._rows_to_dicts(response)]

    def get_event_root(self, event_id: int) -> list[Event]:
        """Walk up to the root event, then return the full tree from that root."""
        response = self._execute(
            """WITH RECURSIVE ancestors AS (
                 SELECT id, parent_event_id FROM events WHERE id = :event_id
                 UNION ALL
                 SELECT e.id, e.parent_event_id
                 FROM events e JOIN ancestors a ON e.id = a.parent_event_id
               )
               SELECT id FROM ancestors WHERE parent_event_id IS NULL""",
            [self._param("event_id", event_id)],
        )
        root_row = self._first_row(response)
        if not root_row:
            return []
        return self.get_event_tree(root_row["id"])

    def _event_from_row(self, row: dict) -> Event:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return Event(
            id=row["id"],
            event_type=row["event_type"],
            source=row.get("source"),
            payload=payload,
            parent_event_id=row.get("parent_event_id"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # MEMORY
    # ═══════════════════════════════════════════════════════════

    def insert_memory(self, mem: MemoryRecord) -> UUID:
        response = self._execute(
            """INSERT INTO memory (id, scope, name, content, provenance)
               VALUES (:id, :scope, :name, :content, :provenance::jsonb)
               ON CONFLICT (scope, name) WHERE name IS NOT NULL
               DO UPDATE SET content = EXCLUDED.content, provenance = EXCLUDED.provenance,
                            updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", mem.id),
                self._param("scope", mem.scope.value),
                self._param("name", mem.name),
                self._param("content", mem.content),
                self._param("provenance", mem.provenance),
            ],
        )
        row = self._first_row(response)
        if row:
            mem.created_at = datetime.fromisoformat(row["created_at"])
            mem.updated_at = datetime.fromisoformat(row["updated_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert memory")

    def get_memory(self, memory_id: UUID) -> MemoryRecord | None:
        response = self._execute(
            "SELECT * FROM memory WHERE id = :id",
            [self._param("id", memory_id)],
        )
        row = self._first_row(response)
        return self._memory_from_row(row) if row else None

    def query_memory(
        self,
        *,
        scope: MemoryScope | None = None,
        name: str | None = None,
        prefix: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        conditions = []
        params = []

        if scope:
            conditions.append("scope = :scope")
            params.append(self._param("scope", scope.value))
        if name:
            conditions.append("name = :name")
            params.append(self._param("name", name))
        if prefix:
            conditions.append("name LIKE :prefix")
            params.append(self._param("prefix", prefix + "%"))

        where = " AND ".join(conditions)
        params.append(self._param("limit", limit))

        response = self._execute(
            f"SELECT * FROM memory WHERE {where} ORDER BY name ASC LIMIT :limit",
            params,
        )
        return [self._memory_from_row(r) for r in self._rows_to_dicts(response)]

    def query_memory_by_prefixes(
        self,
        prefixes: list[str],
    ) -> list[MemoryRecord]:
        """Fetch memory records matching any of the given name prefixes.

        COGENT-scoped records override POLIS-scoped records with the same name.
        Returns deduplicated results sorted by name.
        """
        if not prefixes:
            return []

        conditions = []
        params = []
        for i, prefix in enumerate(prefixes):
            param_name = f"prefix_{i}"
            params.append(self._param(param_name, prefix + "%"))
            conditions.append(f"name LIKE :{param_name}")

        prefix_filter = " OR ".join(conditions)
        response = self._execute(
            f"""SELECT * FROM memory
                WHERE ({prefix_filter})
                ORDER BY scope ASC, name ASC""",
            params,
        )

        seen: dict[str, MemoryRecord] = {}
        for row in self._rows_to_dicts(response):
            record = self._memory_from_row(row)
            if record.name and record.name not in seen:
                seen[record.name] = record
        return sorted(seen.values(), key=lambda r: r.name or "")

    def delete_memory(self, memory_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM memory WHERE id = :id",
            [self._param("id", memory_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def get_memories_by_names(
        self,
        names: list[str],
    ) -> list[MemoryRecord]:
        """Batch fetch memory records by exact name match."""
        if not names:
            return []
        # Build IN clause with individual params
        name_params = []
        conditions = []
        for i, name in enumerate(names):
            param_name = f"name_{i}"
            name_params.append(self._param(param_name, name))
            conditions.append(f":{param_name}")

        in_clause = ", ".join(conditions)

        response = self._execute(
            f"""SELECT * FROM memory
                WHERE name IN ({in_clause})
                ORDER BY scope ASC, name ASC""",
            name_params,
        )
        return [self._memory_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_memories_by_prefix(
        self,
        prefix: str,
        scope: MemoryScope | None = None,
    ) -> int:
        """Delete all memory records matching a name prefix."""
        conditions = ["name LIKE :prefix"]
        params = [self._param("prefix", prefix + "%")]
        if scope:
            conditions.append("scope = :scope")
            params.append(self._param("scope", scope.value))

        where = " AND ".join(conditions)
        response = self._execute(f"DELETE FROM memory WHERE {where}", params)
        return response.get("numberOfRecordsUpdated", 0)

    def _memory_from_row(self, row: dict) -> MemoryRecord:
        provenance = row.get("provenance", {})
        if isinstance(provenance, str):
            provenance = json.loads(provenance)
        return MemoryRecord(
            id=UUID(row["id"]),
            scope=MemoryScope(row["scope"]),
            name=row.get("name"),
            content=row.get("content", ""),
            provenance=provenance,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # PROGRAMS
    # ═══════════════════════════════════════════════════════════

    def upsert_program(self, program: Program) -> UUID:
        """Insert or update a program by name."""
        response = self._execute(
            """INSERT INTO programs
                   (id, name, program_type, content, includes, tools, memory_keys, metadata, runner)
               VALUES (:id, :name, :program_type, :content, :includes::jsonb,
                       :tools::jsonb, :memory_keys::jsonb, :metadata::jsonb, :runner)
               ON CONFLICT (name)
               DO UPDATE SET program_type = EXCLUDED.program_type, content = EXCLUDED.content,
                            includes = EXCLUDED.includes, tools = EXCLUDED.tools,
                            memory_keys = EXCLUDED.memory_keys, metadata = EXCLUDED.metadata,
                            runner = EXCLUDED.runner,
                            updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", program.id),
                self._param("name", program.name),
                self._param("program_type", program.program_type.value),
                self._param("content", program.content),
                self._param("includes", program.includes),
                self._param("tools", program.tools),
                self._param("memory_keys", program.memory_keys),
                self._param("metadata", program.metadata),
                self._param("runner", program.runner),
            ],
        )
        row = self._first_row(response)
        if row:
            program.created_at = datetime.fromisoformat(row["created_at"])
            program.updated_at = datetime.fromisoformat(row["updated_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert program")

    def get_program(self, name: str) -> Program | None:
        """Get a program by name."""
        response = self._execute(
            "SELECT * FROM programs WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._program_from_row(row) if row else None

    def list_programs(self) -> list[Program]:
        response = self._execute("SELECT * FROM programs ORDER BY name")
        return [self._program_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_program(self, name: str) -> bool:
        response = self._execute(
            "DELETE FROM programs WHERE name = :name",
            [self._param("name", name)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _program_from_row(self, row: dict) -> Program:
        includes = row.get("includes", [])
        if isinstance(includes, str):
            includes = json.loads(includes)
        tools = row.get("tools", [])
        if isinstance(tools, str):
            tools = json.loads(tools)
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return Program(
            id=UUID(row["id"]),
            name=row["name"],
            program_type=ProgramType(row.get("program_type", "prompt")),
            content=row.get("content", ""),
            includes=includes,
            tools=tools,
            memory_keys=(
                json.loads(row["memory_keys"])
                if isinstance(row.get("memory_keys"), str)
                else row.get("memory_keys", [])
            ),
            metadata=metadata,
            runner=row.get("runner"),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None,
        )

    # ═══════════════════════════════════════════════════════════
    # CHANNELS
    # ═══════════════════════════════════════════════════════════

    def upsert_channel(self, channel: Channel) -> UUID:
        response = self._execute(
            """INSERT INTO channels (id, type, name, external_id, secret_arn, config, enabled)
               VALUES (:id, :type, :name, :external_id, :secret_arn, :config::jsonb, :enabled)
               ON CONFLICT (type, name)
               DO UPDATE SET external_id = EXCLUDED.external_id, secret_arn = EXCLUDED.secret_arn,
                            config = EXCLUDED.config, enabled = EXCLUDED.enabled
               RETURNING id, created_at""",
            [
                self._param("id", channel.id),
                self._param("type", channel.type.value),
                self._param("name", channel.name),
                self._param("external_id", channel.external_id),
                self._param("secret_arn", channel.secret_arn),
                self._param("config", channel.config),
                self._param("enabled", channel.enabled),
            ],
        )
        row = self._first_row(response)
        if row:
            channel.created_at = datetime.fromisoformat(row["created_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert channel")

    def list_channels(self) -> list[Channel]:
        response = self._execute(
            "SELECT * FROM channels ORDER BY type, name",
        )
        return [self._channel_from_row(r) for r in self._rows_to_dicts(response)]

    def _channel_from_row(self, row: dict) -> Channel:
        config = row.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        return Channel(
            id=UUID(row["id"]),
            type=ChannelType(row["type"]),
            name=row["name"],
            external_id=row.get("external_id"),
            secret_arn=row.get("secret_arn"),
            config=config,
            enabled=row["enabled"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # TASKS
    # ═══════════════════════════════════════════════════════════

    def create_task(self, task: Task) -> UUID:
        response = self._execute(
            """INSERT INTO tasks (id, name, description, program_name, content,
                                  memory_keys, tools, status, priority, runner,
                                  clear_context, resources, parent_task_id,
                                  creator, source_event, limits, metadata)
               VALUES (:id, :name, :description, :program_name, :content,
                       :memory_keys::jsonb, :tools::jsonb, :status, :priority, :runner,
                       :clear_context, :resources::jsonb, :parent_task_id,
                       :creator, :source_event, :limits::jsonb, :metadata::jsonb)
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", task.id),
                self._param("name", task.name),
                self._param("description", task.description),
                self._param("program_name", task.program_name),
                self._param("content", task.content),
                self._param("memory_keys", task.memory_keys),
                self._param("tools", task.tools),
                self._param("status", task.status.value),
                self._param("priority", task.priority),
                self._param("runner", task.runner),
                self._param("clear_context", task.clear_context),
                self._param("resources", task.resources),
                self._param("parent_task_id", task.parent_task_id),
                self._param("creator", task.creator),
                self._param("source_event", task.source_event),
                self._param("limits", task.limits),
                self._param("metadata", task.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            task.created_at = datetime.fromisoformat(row["created_at"])
            task.updated_at = datetime.fromisoformat(row["updated_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to create task")

    def upsert_task(self, task: Task, *, update_priority: bool = False) -> UUID:
        """Upsert task by name. Priority preserved unless update_priority=True."""
        priority_clause = "priority = EXCLUDED.priority," if update_priority else ""
        response = self._execute(
            f"""INSERT INTO tasks (id, name, description, program_name, content,
                                  memory_keys, tools, status, priority, runner,
                                  clear_context, resources, parent_task_id,
                                  creator, source_event, limits, metadata)
               VALUES (:id, :name, :description, :program_name, :content,
                       :memory_keys::jsonb, :tools::jsonb, :status, :priority, :runner,
                       :clear_context, :resources::jsonb, :parent_task_id,
                       :creator, :source_event, :limits::jsonb, :metadata::jsonb)
               ON CONFLICT (name) DO UPDATE SET
                   description = EXCLUDED.description,
                   program_name = EXCLUDED.program_name,
                   content = EXCLUDED.content,
                   memory_keys = EXCLUDED.memory_keys,
                   tools = EXCLUDED.tools,
                   {priority_clause}
                   runner = EXCLUDED.runner,
                   clear_context = EXCLUDED.clear_context,
                   resources = EXCLUDED.resources,
                   limits = EXCLUDED.limits,
                   metadata = EXCLUDED.metadata,
                   updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", task.id),
                self._param("name", task.name),
                self._param("description", task.description),
                self._param("program_name", task.program_name),
                self._param("content", task.content),
                self._param("memory_keys", task.memory_keys),
                self._param("tools", task.tools),
                self._param("status", task.status.value),
                self._param("priority", task.priority),
                self._param("runner", task.runner),
                self._param("clear_context", task.clear_context),
                self._param("resources", task.resources),
                self._param("parent_task_id", task.parent_task_id),
                self._param("creator", task.creator),
                self._param("source_event", task.source_event),
                self._param("limits", task.limits),
                self._param("metadata", task.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            task.created_at = datetime.fromisoformat(row["created_at"])
            task.updated_at = datetime.fromisoformat(row["updated_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert task")

    def get_task(self, task_id: UUID) -> Task | None:
        response = self._execute(
            "SELECT * FROM tasks WHERE id = :id",
            [self._param("id", task_id)],
        )
        row = self._first_row(response)
        return self._task_from_row(row) if row else None

    def get_task_by_name(self, name: str) -> Task | None:
        response = self._execute(
            "SELECT * FROM tasks WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._task_from_row(row) if row else None

    def update_task_status(self, task_id: UUID, status: TaskStatus) -> bool:
        if status == TaskStatus.COMPLETED:
            response = self._execute(
                """UPDATE tasks SET status = :status, completed_at = now(), updated_at = now()
                   WHERE id = :id""",
                [
                    self._param("id", task_id),
                    self._param("status", status.value),
                ],
            )
        else:
            response = self._execute(
                "UPDATE tasks SET status = :status, updated_at = now() WHERE id = :id",
                [
                    self._param("id", task_id),
                    self._param("status", status.value),
                ],
            )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_task(self, task: Task) -> bool:
        if task.status == TaskStatus.COMPLETED and task.completed_at:
            response = self._execute(
                """UPDATE tasks SET name = :name, description = :description,
                          status = :status, priority = :priority,
                          metadata = :metadata::jsonb, updated_at = now(),
                          completed_at = :completed_at
                   WHERE id = :id""",
                [
                    self._param("id", task.id),
                    self._param("name", task.name),
                    self._param("description", task.description),
                    self._param("status", task.status.value),
                    self._param("priority", task.priority),
                    self._param("metadata", task.metadata),
                    self._param("completed_at", task.completed_at),
                ],
            )
        else:
            response = self._execute(
                """UPDATE tasks SET name = :name, description = :description,
                          status = :status, priority = :priority,
                          metadata = :metadata::jsonb, updated_at = now()
                   WHERE id = :id""",
                [
                    self._param("id", task.id),
                    self._param("name", task.name),
                    self._param("description", task.description),
                    self._param("status", task.status.value),
                    self._param("priority", task.priority),
                    self._param("metadata", task.metadata),
                ],
            )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def delete_task(self, task_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM tasks WHERE id = :id",
            [self._param("id", task_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[Task]:
        if status:
            response = self._execute(
                """SELECT * FROM tasks WHERE status = :status
                   ORDER BY priority DESC, created_at DESC LIMIT :limit""",
                [
                    self._param("status", status.value),
                    self._param("limit", limit),
                ],
            )
        else:
            response = self._execute(
                """SELECT * FROM tasks
                   ORDER BY priority DESC, created_at DESC LIMIT :limit""",
                [self._param("limit", limit)],
            )
        return [self._task_from_row(r) for r in self._rows_to_dicts(response)]

    def _task_from_row(self, row: dict) -> Task:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        limits = row.get("limits", {})
        if isinstance(limits, str):
            limits = json.loads(limits)
        memory_keys = row.get("memory_keys", [])
        if isinstance(memory_keys, str):
            memory_keys = json.loads(memory_keys)
        tools = row.get("tools", [])
        if isinstance(tools, str):
            tools = json.loads(tools)
        resources = row.get("resources", [])
        if isinstance(resources, str):
            resources = json.loads(resources)
        return Task(
            id=UUID(row["id"]),
            name=row["name"],
            description=row.get("description", ""),
            program_name=row.get("program_name", "do-content"),
            content=row.get("content", ""),
            memory_keys=memory_keys,
            tools=tools,
            status=TaskStatus(row["status"]),
            priority=row.get("priority", 0.0),
            runner=row.get("runner"),
            clear_context=row.get("clear_context", False),
            recurrent=row.get("recurrent", False),
            resources=resources,
            parent_task_id=UUID(row["parent_task_id"]) if row.get("parent_task_id") else None,
            creator=row.get("creator", ""),
            source_event=row.get("source_event"),
            limits=limits,
            metadata=metadata,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None,
        )

    # ═══════════════════════════════════════════════════════════
    # CONVERSATIONS
    # ═══════════════════════════════════════════════════════════

    def upsert_conversation(self, conv: Conversation) -> UUID:
        response = self._execute(
            """INSERT INTO conversations (id, context_key, channel_id, status,
                                          cli_session_id, metadata)
               VALUES (:id, :context_key, :channel_id, :status, :cli_session_id, :metadata::jsonb)
               ON CONFLICT (id)
               DO UPDATE SET status = EXCLUDED.status, cli_session_id = EXCLUDED.cli_session_id,
                            metadata = EXCLUDED.metadata, last_active = now()
               RETURNING id, started_at, last_active""",
            [
                self._param("id", conv.id),
                self._param("context_key", conv.context_key),
                self._param("channel_id", conv.channel_id),
                self._param("status", conv.status.value),
                self._param("cli_session_id", conv.cli_session_id),
                self._param("metadata", conv.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            conv.started_at = datetime.fromisoformat(row["started_at"])
            conv.last_active = datetime.fromisoformat(row["last_active"])
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert conversation")

    def get_conversation_by_context(self, context_key: str) -> Conversation | None:
        response = self._execute(
            """SELECT * FROM conversations
               WHERE context_key = :context_key AND status != 'closed'
               ORDER BY last_active DESC LIMIT 1""",
            [
                self._param("context_key", context_key),
            ],
        )
        row = self._first_row(response)
        return self._conversation_from_row(row) if row else None

    def list_conversations(
        self,
        *,
        status: ConversationStatus | None = None,
    ) -> list[Conversation]:
        if status:
            response = self._execute(
                """SELECT * FROM conversations WHERE status = :status
                   ORDER BY last_active DESC""",
                [
                    self._param("status", status.value),
                ],
            )
        else:
            response = self._execute(
                "SELECT * FROM conversations ORDER BY last_active DESC",
            )
        return [self._conversation_from_row(r) for r in self._rows_to_dicts(response)]

    def close_conversation(self, conversation_id: UUID) -> bool:
        response = self._execute(
            "UPDATE conversations SET status = 'closed' WHERE id = :id",
            [self._param("id", conversation_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _conversation_from_row(self, row: dict) -> Conversation:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Conversation(
            id=UUID(row["id"]),
            context_key=row.get("context_key", ""),
            channel_id=UUID(row["channel_id"]) if row.get("channel_id") else None,
            status=ConversationStatus(row["status"]),
            cli_session_id=row.get("cli_session_id"),
            started_at=datetime.fromisoformat(row["started_at"]),
            last_active=datetime.fromisoformat(row["last_active"]),
            metadata=metadata,
        )

    # ═══════════════════════════════════════════════════════════
    # RUNS
    # ═══════════════════════════════════════════════════════════

    def insert_run(self, run: Run) -> UUID:
        response = self._execute(
            """INSERT INTO runs (id, program_name, task_id, trigger_id, conversation_id,
                                 status, tokens_input, tokens_output, cost_usd,
                                 duration_ms, events_emitted, error, model_version)
               VALUES (:id, :program_name, :task_id, :trigger_id, :conversation_id,
                       :status, :tokens_input, :tokens_output, :cost_usd,
                       :duration_ms, :events_emitted::jsonb, :error, :model_version)
               RETURNING id, started_at""",
            [
                self._param("id", run.id),
                self._param("program_name", run.program_name),
                self._param("task_id", run.task_id),
                self._param("trigger_id", run.trigger_id),
                self._param("conversation_id", run.conversation_id),
                self._param("status", run.status.value),
                self._param("tokens_input", run.tokens_input),
                self._param("tokens_output", run.tokens_output),
                self._param("cost_usd", run.cost_usd),
                self._param("duration_ms", run.duration_ms),
                self._param("events_emitted", run.events_emitted),
                self._param("error", run.error),
                self._param("model_version", run.model_version),
            ],
        )
        row = self._first_row(response)
        if row:
            run.started_at = datetime.fromisoformat(row["started_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert run")

    def update_run(self, run: Run) -> bool:
        response = self._execute(
            """UPDATE runs SET status = :status, tokens_input = :tokens_input,
                      tokens_output = :tokens_output, cost_usd = :cost_usd,
                      duration_ms = :duration_ms, events_emitted = :events_emitted::jsonb,
                      error = :error, model_version = :model_version, completed_at = :completed_at
               WHERE id = :id""",
            [
                self._param("id", run.id),
                self._param("status", run.status.value),
                self._param("tokens_input", run.tokens_input),
                self._param("tokens_output", run.tokens_output),
                self._param("cost_usd", run.cost_usd),
                self._param("duration_ms", run.duration_ms),
                self._param("events_emitted", run.events_emitted),
                self._param("error", run.error),
                self._param("model_version", run.model_version),
                self._param("completed_at", run.completed_at),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def query_runs(
        self,
        *,
        program_name: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> list[Run]:
        conditions = []
        params = []

        if program_name:
            conditions.append("program_name = :program_name")
            params.append(self._param("program_name", program_name))
        if status:
            conditions.append("status = :status")
            params.append(self._param("status", status.value))

        if conditions:
            where = " AND ".join(conditions)
            where_clause = f"WHERE {where}"
        else:
            where_clause = ""
        params.append(self._param("limit", limit))

        response = self._execute(
            f"""SELECT * FROM runs {where_clause}
                ORDER BY started_at DESC LIMIT :limit""",
            params,
        )
        return [self._run_from_row(r) for r in self._rows_to_dicts(response)]

    def _run_from_row(self, row: dict) -> Run:
        events = row.get("events_emitted", [])
        if isinstance(events, str):
            events = json.loads(events)
        return Run(
            id=UUID(row["id"]),
            program_name=row["program_name"],
            task_id=UUID(row["task_id"]) if row.get("task_id") else None,
            trigger_id=UUID(row["trigger_id"]) if row.get("trigger_id") else None,
            conversation_id=UUID(row["conversation_id"]) if row.get("conversation_id") else None,
            status=RunStatus(row["status"]),
            tokens_input=row.get("tokens_input", 0),
            tokens_output=row.get("tokens_output", 0),
            cost_usd=Decimal(row.get("cost_usd", "0")),
            duration_ms=row.get("duration_ms"),
            events_emitted=events,
            error=row.get("error"),
            model_version=row.get("model_version"),
            started_at=datetime.fromisoformat(row["started_at"]) if row.get("started_at") else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None,
        )

    # ═══════════════════════════════════════════════════════════
    # TRACES
    # ═══════════════════════════════════════════════════════════

    def insert_trace(self, trace: Trace) -> UUID:
        response = self._execute(
            """INSERT INTO traces (id, run_id, tool_calls, memory_ops, model_version)
               VALUES (:id, :run_id, :tool_calls::jsonb, :memory_ops::jsonb, :model_version)
               RETURNING id, created_at""",
            [
                self._param("id", trace.id),
                self._param("run_id", trace.run_id),
                self._param("tool_calls", trace.tool_calls),
                self._param("memory_ops", trace.memory_ops),
                self._param("model_version", trace.model_version),
            ],
        )
        row = self._first_row(response)
        if row:
            trace.created_at = datetime.fromisoformat(row["created_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert trace")

    def get_traces(self, run_id: UUID) -> list[Trace]:
        response = self._execute(
            "SELECT * FROM traces WHERE run_id = :run_id ORDER BY created_at",
            [self._param("run_id", run_id)],
        )
        return [self._trace_from_row(r) for r in self._rows_to_dicts(response)]

    def _trace_from_row(self, row: dict) -> Trace:
        tool_calls = row.get("tool_calls", [])
        if isinstance(tool_calls, str):
            tool_calls = json.loads(tool_calls)
        memory_ops = row.get("memory_ops", [])
        if isinstance(memory_ops, str):
            memory_ops = json.loads(memory_ops)
        return Trace(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            tool_calls=tool_calls,
            memory_ops=memory_ops,
            model_version=row.get("model_version"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # TRIGGERS
    # ═══════════════════════════════════════════════════════════

    def insert_trigger(self, trigger: Trigger) -> UUID:
        response = self._execute(
            """INSERT INTO triggers (id, program_name, event_pattern, priority, config, enabled)
               VALUES (:id, :program_name, :event_pattern, :priority, :config::jsonb, :enabled)
               RETURNING id, created_at""",
            [
                self._param("id", trigger.id),
                self._param("program_name", trigger.program_name),
                self._param("event_pattern", trigger.event_pattern),
                self._param("priority", trigger.priority),
                self._param("config", trigger.config.model_dump()),
                self._param("enabled", trigger.enabled),
            ],
        )
        row = self._first_row(response)
        if row:
            trigger.created_at = datetime.fromisoformat(row["created_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert trigger")

    def get_trigger(self, trigger_id: UUID) -> Trigger | None:
        response = self._execute(
            "SELECT * FROM triggers WHERE id = :id",
            [self._param("id", trigger_id)],
        )
        row = self._first_row(response)
        return self._trigger_from_row(row) if row else None

    def list_triggers(self, *, enabled_only: bool = True, program_name: str | None = None) -> list[Trigger]:
        conditions = []
        params = []
        if enabled_only:
            conditions.append("enabled = true")
        if program_name:
            conditions.append("program_name = :program_name")
            params.append(self._param("program_name", program_name))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        response = self._execute(
            f"SELECT * FROM triggers{where} ORDER BY priority",
            params or None,
        )
        return [self._trigger_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_trigger(self, trigger_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM triggers WHERE id = :id",
            [self._param("id", trigger_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_trigger_enabled(self, trigger_id: UUID, enabled: bool) -> bool:
        response = self._execute(
            "UPDATE triggers SET enabled = :enabled WHERE id = :id",
            [
                self._param("id", trigger_id),
                self._param("enabled", enabled),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _trigger_from_row(self, row: dict) -> Trigger:
        config = row.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        return Trigger(
            id=UUID(row["id"]),
            program_name=row["program_name"],
            event_pattern=row.get("event_pattern", ""),
            priority=row.get("priority", 10),
            config=TriggerConfig(**config) if config else TriggerConfig(),
            enabled=row.get("enabled", True),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # CRON
    # ═══════════════════════════════════════════════════════════

    def insert_cron(self, cron: Cron) -> UUID:
        response = self._execute(
            """INSERT INTO cron (id, cron_expression, event_pattern, enabled, metadata)
               VALUES (:id, :cron_expression, :event_pattern, :enabled, :metadata::jsonb)
               RETURNING id, created_at""",
            [
                self._param("id", cron.id),
                self._param("cron_expression", cron.cron_expression),
                self._param("event_pattern", cron.event_pattern),
                self._param("enabled", cron.enabled),
                self._param("metadata", cron.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            cron.created_at = datetime.fromisoformat(row["created_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert cron")

    def list_cron(self, *, enabled_only: bool = False) -> list[Cron]:
        if enabled_only:
            response = self._execute(
                "SELECT * FROM cron WHERE enabled = true ORDER BY created_at"
            )
        else:
            response = self._execute("SELECT * FROM cron ORDER BY created_at")
        return [self._cron_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_cron(self, cron_id: UUID) -> bool:
        response = self._execute(
            "DELETE FROM cron WHERE id = :id",
            [self._param("id", cron_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        response = self._execute(
            "UPDATE cron SET enabled = :enabled WHERE id = :id",
            [
                self._param("id", cron_id),
                self._param("enabled", enabled),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _cron_from_row(self, row: dict) -> Cron:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Cron(
            id=UUID(row["id"]),
            cron_expression=row["cron_expression"],
            event_pattern=row["event_pattern"],
            enabled=row.get("enabled", True),
            metadata=metadata,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════

    def create_alert(self, alert: Alert) -> UUID:
        response = self._execute(
            """INSERT INTO alerts (id, severity, alert_type, source, message, metadata)
               VALUES (:id, :severity, :alert_type, :source, :message, :metadata::jsonb)
               RETURNING id, created_at""",
            [
                self._param("id", alert.id),
                self._param("severity", alert.severity.value),
                self._param("alert_type", alert.alert_type),
                self._param("source", alert.source),
                self._param("message", alert.message),
                self._param("metadata", alert.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            alert.created_at = datetime.fromisoformat(row["created_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to create alert")

    def get_unresolved_alerts(self) -> list[Alert]:
        response = self._execute(
            """SELECT * FROM alerts WHERE resolved_at IS NULL
               ORDER BY created_at DESC""",
        )
        return [self._alert_from_row(r) for r in self._rows_to_dicts(response)]

    def resolve_alert(self, alert_id: UUID) -> bool:
        response = self._execute(
            "UPDATE alerts SET resolved_at = now() WHERE id = :id",
            [self._param("id", alert_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def resolve_all_alerts(self) -> int:
        response = self._execute(
            "UPDATE alerts SET resolved_at = now() WHERE resolved_at IS NULL",
        )
        return response.get("numberOfRecordsUpdated", 0)

    def get_resolved_alerts(self, limit: int = 25) -> list[Alert]:
        response = self._execute(
            """SELECT * FROM alerts WHERE resolved_at IS NOT NULL
               ORDER BY resolved_at DESC LIMIT :limit""",
            [self._param("limit", limit)],
        )
        return [self._alert_from_row(r) for r in self._rows_to_dicts(response)]

    def _alert_from_row(self, row: dict) -> Alert:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Alert(
            id=UUID(row["id"]),
            severity=AlertSeverity(row["severity"]),
            alert_type=row["alert_type"],
            source=row["source"],
            message=row["message"],
            metadata=metadata,
            acknowledged_at=datetime.fromisoformat(row["acknowledged_at"]) if row.get("acknowledged_at") else None,
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row.get("resolved_at") else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # BUDGET
    # ═══════════════════════════════════════════════════════════

    def get_or_create_budget(
        self,
        period: BudgetPeriod,
        period_start: date,
        *,
        token_limit: int = 0,
        cost_limit_usd: Decimal = Decimal("0"),
    ) -> Budget:
        response = self._execute(
            """INSERT INTO budget (period, period_start, token_limit, cost_limit_usd)
               VALUES (:period, :period_start, :token_limit, :cost_limit_usd)
               ON CONFLICT (period, period_start) DO NOTHING
               RETURNING *""",
            [
                self._param("period", period.value),
                self._param("period_start", period_start),
                self._param("token_limit", token_limit),
                self._param("cost_limit_usd", cost_limit_usd),
            ],
        )
        row = self._first_row(response)
        if row:
            return self._budget_from_row(row)

        response = self._execute(
            "SELECT * FROM budget WHERE period = :period AND period_start = :period_start",
            [
                self._param("period", period.value),
                self._param("period_start", period_start),
            ],
        )
        row = self._first_row(response)
        if not row:
            raise RuntimeError("Failed to get or create budget")
        return self._budget_from_row(row)

    def record_spend(
        self,
        period: BudgetPeriod,
        period_start: date,
        *,
        tokens: int = 0,
        cost_usd: Decimal = Decimal("0"),
    ) -> Budget:
        response = self._execute(
            """UPDATE budget SET tokens_spent = tokens_spent + :tokens,
                      cost_spent_usd = cost_spent_usd + :cost_usd, updated_at = now()
               WHERE period = :period AND period_start = :period_start
               RETURNING *""",
            [
                self._param("period", period.value),
                self._param("period_start", period_start),
                self._param("tokens", tokens),
                self._param("cost_usd", cost_usd),
            ],
        )
        row = self._first_row(response)
        if not row:
            raise RuntimeError("Failed to record spend")
        return self._budget_from_row(row)

    def check_budget(self, period: BudgetPeriod, period_start: date) -> Budget | None:
        response = self._execute(
            "SELECT * FROM budget WHERE period = :period AND period_start = :period_start",
            [
                self._param("period", period.value),
                self._param("period_start", period_start),
            ],
        )
        row = self._first_row(response)
        return self._budget_from_row(row) if row else None

    def _budget_from_row(self, row: dict) -> Budget:
        return Budget(
            id=UUID(row["id"]),
            period=BudgetPeriod(row["period"]),
            period_start=(
                date.fromisoformat(row["period_start"]) if isinstance(row["period_start"], str) else row["period_start"]
            ),
            tokens_spent=row.get("tokens_spent", 0),
            cost_spent_usd=Decimal(row.get("cost_spent_usd", "0")),
            token_limit=row.get("token_limit", 0),
            cost_limit_usd=Decimal(row.get("cost_limit_usd", "0")),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # RESOURCES
    # ═══════════════════════════════════════════════════════════

    def upsert_resource(self, resource: Resource) -> str:
        """Insert or update a resource by name."""
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
            resource.created_at = datetime.fromisoformat(row["created_at"])
            return row["name"]
        raise RuntimeError("Failed to upsert resource")

    def get_resource(self, name: str) -> Resource | None:
        response = self._execute(
            "SELECT * FROM resources WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._resource_from_row(row) if row else None

    def list_resources(self) -> list[Resource]:
        response = self._execute("SELECT * FROM resources ORDER BY name")
        return [self._resource_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_resource(self, name: str) -> bool:
        response = self._execute(
            "DELETE FROM resources WHERE name = :name",
            [self._param("name", name)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _resource_from_row(self, row: dict) -> Resource:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Resource(
            name=row["name"],
            resource_type=ResourceType(row["resource_type"]),
            capacity=row.get("capacity", 1.0),
            metadata=metadata,
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
        )

    def insert_resource_usage(self, usage: ResourceUsage) -> int:
        """Record resource usage for a run."""
        response = self._execute(
            """INSERT INTO resource_usage (resource_name, run_id, amount)
               VALUES (:resource_name, :run_id, :amount)
               RETURNING id, created_at""",
            [
                self._param("resource_name", usage.resource_name),
                self._param("run_id", usage.run_id),
                self._param("amount", usage.amount),
            ],
        )
        row = self._first_row(response)
        if row:
            usage.id = row["id"]
            usage.created_at = datetime.fromisoformat(row["created_at"])
            return row["id"]
        raise RuntimeError("Failed to insert resource usage")

    def get_consumable_usage(self, resource_name: str) -> float:
        """Sum total usage for a consumable resource."""
        response = self._execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM resource_usage WHERE resource_name = :name",
            [self._param("name", resource_name)],
        )
        row = self._first_row(response)
        return float(row["total"]) if row else 0.0

    def get_pool_usage(self, resource_name: str) -> int:
        """Count running tasks that consume this pool resource."""
        response = self._execute(
            """SELECT COUNT(*) as cnt FROM tasks
               WHERE status = 'running'
               AND (
                   runner = :name
                   OR :name = 'concurrent-tasks'
                   OR resources::jsonb ? :name
               )""",
            [self._param("name", resource_name)],
        )
        row = self._first_row(response)
        return int(row["cnt"]) if row else 0

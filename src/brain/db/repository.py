"""Synchronous PostgreSQL repository using RDS Data API: CRUD for all 12 tables."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import boto3

from brain.db.models import (
    Alert,
    AlertSeverity,
    Budget,
    BudgetPeriod,
    Conversation,
    ConversationStatus,
    Cron,
    Event,
    Memory,
    MemoryVersion,
    Program,
    Resource,
    ResourceType,
    ResourceUsage,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Trace,
    Tool,
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
        """Create repository from arguments or environment variables.

        Callers must ensure AWS credentials are set for the polis account
        (where all cogent databases live). The CLI does this via
        _ensure_db_env(); the dashboard container has credentials from its
        ECS task role.
        """
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

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
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
            param["typeHint"] = "UUID"
        elif isinstance(value, datetime):
            param["value"] = {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S.%f")}
        elif isinstance(value, date):
            param["value"] = {"stringValue": value.isoformat()}
            param["typeHint"] = "DATE"
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

    def append_event(self, event: Event, *, status: str = "sent") -> int:
        response = self._execute(
            """INSERT INTO events (event_type, source, payload, parent_event_id, status)
               VALUES (:event_type, :source, :payload::jsonb, :parent_event_id, :status)
               RETURNING id, created_at""",
            [
                self._param("event_type", event.event_type),
                self._param("source", event.source),
                self._param("payload", event.payload),
                self._param("parent_event_id", event.parent_event_id),
                self._param("status", status),
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

    def get_proposed_events(self, *, limit: int = 50) -> list[Event]:
        """Fetch events with status='proposed' for dispatch."""
        response = self._execute(
            """SELECT id, event_type, source, payload, parent_event_id, status, created_at
               FROM events WHERE status = 'proposed'
               ORDER BY id ASC LIMIT :limit""",
            [self._param("limit", limit)],
        )
        return [self._event_from_row(r) for r in self._rows_to_dicts(response)]

    def mark_event_sent(self, event_id: int) -> bool:
        """Mark an event as sent after publishing to EventBridge."""
        response = self._execute(
            "UPDATE events SET status = 'sent' WHERE id = :id",
            [self._param("id", event_id)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

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
            status=row.get("status", "sent"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ═══════════════════════════════════════════════════════════
    # MEMORY (versioned)
    # ═══════════════════════════════════════════════════════════

    def _memory_from_rows(self, rows: list[dict]) -> Memory | None:
        """Build a Memory with versions dict from JOIN query rows."""
        if not rows:
            return None
        first = rows[0]
        includes_raw = first.get("includes", [])
        if isinstance(includes_raw, str):
            includes_raw = json.loads(includes_raw)
        mem = Memory(
            id=UUID(first["id"]),
            name=first["name"],
            active_version=first["active_version"],
            includes=includes_raw or [],
            created_at=datetime.fromisoformat(first["created_at"]) if first.get("created_at") else None,
            modified_at=datetime.fromisoformat(first["modified_at"]) if first.get("modified_at") else None,
        )
        for row in rows:
            if row.get("version") is not None:
                mv = MemoryVersion(
                    id=UUID(row["mv_id"]) if row.get("mv_id") else uuid4(),
                    memory_id=mem.id,
                    version=row["version"],
                    read_only=row.get("read_only", False),
                    content=row.get("content", ""),
                    source=row.get("source", "cogent"),
                    created_at=datetime.fromisoformat(row["mv_created_at"]) if row.get("mv_created_at") else None,
                )
                mem.versions[mv.version] = mv
        return mem

    def insert_memory(self, mem: Memory) -> UUID:
        """Insert a new versioned memory record."""
        response = self._execute(
            """INSERT INTO memory (id, name, active_version, includes)
               VALUES (:id, :name, :active_version, :includes::jsonb)
               ON CONFLICT (name)
               DO UPDATE SET active_version = EXCLUDED.active_version,
                            includes = EXCLUDED.includes,
                            modified_at = now()
               RETURNING id, created_at, modified_at""",
            [
                self._param("id", mem.id),
                self._param("name", mem.name),
                self._param("active_version", mem.active_version),
                self._param("includes", mem.includes),
            ],
        )
        row = self._first_row(response)
        if row:
            mem.created_at = datetime.fromisoformat(row["created_at"])
            mem.modified_at = datetime.fromisoformat(row["modified_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to insert memory")

    def get_memory_by_name(self, name: str) -> Memory | None:
        """Get a versioned memory by name, with all versions populated."""
        response = self._execute(
            """SELECT m.id, m.name, m.active_version, m.includes, m.created_at, m.modified_at,
                      mv.id as mv_id, mv.version, mv.read_only, mv.content,
                      mv.source, mv.created_at as mv_created_at
               FROM memory m
               LEFT JOIN memory_version mv ON mv.memory_id = m.id
               WHERE m.name = :name""",
            [self._param("name", name)],
        )
        rows = self._rows_to_dicts(response)
        return self._memory_from_rows(rows)

    def get_memory_by_id(self, memory_id: UUID) -> Memory | None:
        """Get a versioned memory by ID, with all versions populated."""
        response = self._execute(
            """SELECT m.id, m.name, m.active_version, m.includes, m.created_at, m.modified_at,
                      mv.id as mv_id, mv.version, mv.read_only, mv.content,
                      mv.source, mv.created_at as mv_created_at
               FROM memory m
               LEFT JOIN memory_version mv ON mv.memory_id = m.id
               WHERE m.id = :id""",
            [self._param("id", memory_id)],
        )
        rows = self._rows_to_dicts(response)
        return self._memory_from_rows(rows)

    def insert_memory_version(self, mv: MemoryVersion) -> None:
        """Insert a new memory version row."""
        self._execute(
            """INSERT INTO memory_version (id, memory_id, version, read_only, content, source)
               VALUES (:id, :memory_id, :version, :read_only, :content, :source)""",
            [
                self._param("id", mv.id),
                self._param("memory_id", mv.memory_id),
                self._param("version", mv.version),
                self._param("read_only", mv.read_only),
                self._param("content", mv.content),
                self._param("source", mv.source),
            ],
        )
        # Update modified_at on parent memory
        self._execute(
            "UPDATE memory SET modified_at = now() WHERE id = :id",
            [self._param("id", mv.memory_id)],
        )

    def get_memory_version(self, memory_id: UUID, version: int) -> MemoryVersion | None:
        """Get a specific version of a memory."""
        response = self._execute(
            """SELECT * FROM memory_version
               WHERE memory_id = :memory_id AND version = :version""",
            [
                self._param("memory_id", memory_id),
                self._param("version", version),
            ],
        )
        row = self._first_row(response)
        if not row:
            return None
        return MemoryVersion(
            id=UUID(row["id"]),
            memory_id=UUID(row["memory_id"]),
            version=row["version"],
            read_only=row.get("read_only", False),
            content=row.get("content", ""),
            source=row.get("source", "cogent"),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
        )

    def get_max_version(self, memory_id: UUID) -> int:
        """Return the highest version number for a memory, or 0 if none."""
        response = self._execute(
            "SELECT COALESCE(MAX(version), 0) AS max_v FROM memory_version WHERE memory_id = :memory_id",
            [self._param("memory_id", memory_id)],
        )
        row = self._first_row(response)
        return row["max_v"] if row else 0

    def list_memory_versions(self, memory_id: UUID) -> list[MemoryVersion]:
        """List all versions for a memory, ordered by version."""
        response = self._execute(
            "SELECT * FROM memory_version WHERE memory_id = :memory_id ORDER BY version",
            [self._param("memory_id", memory_id)],
        )
        results = []
        for row in self._rows_to_dicts(response):
            results.append(MemoryVersion(
                id=UUID(row["id"]),
                memory_id=UUID(row["memory_id"]),
                version=row["version"],
                read_only=row.get("read_only", False),
                content=row.get("content", ""),
                source=row.get("source", "cogent"),
                created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            ))
        return results

    def update_active_version(self, memory_id: UUID, version: int) -> None:
        """Set the active version for a memory."""
        self._execute(
            "UPDATE memory SET active_version = :version, modified_at = now() WHERE id = :id",
            [
                self._param("id", memory_id),
                self._param("version", version),
            ],
        )

    def update_version_read_only(self, memory_id: UUID, version: int, read_only: bool) -> None:
        """Set the read_only flag on a specific memory version."""
        self._execute(
            """UPDATE memory_version SET read_only = :read_only
               WHERE memory_id = :memory_id AND version = :version""",
            [
                self._param("memory_id", memory_id),
                self._param("version", version),
                self._param("read_only", read_only),
            ],
        )

    def update_memory_includes(self, memory_id: UUID, includes: list[str]) -> None:
        """Update the includes list on a memory."""
        self._execute(
            "UPDATE memory SET includes = :includes::jsonb, modified_at = now() WHERE id = :id",
            [
                self._param("id", memory_id),
                self._param("includes", includes),
            ],
        )

    def update_memory_name(self, memory_id: UUID, new_name: str) -> None:
        """Rename a memory."""
        self._execute(
            "UPDATE memory SET name = :name, modified_at = now() WHERE id = :id",
            [
                self._param("id", memory_id),
                self._param("name", new_name),
            ],
        )

    def delete_memory(self, memory_id: UUID) -> None:
        """Delete a versioned memory (CASCADE removes versions)."""
        self._execute(
            "DELETE FROM memory WHERE id = :id",
            [self._param("id", memory_id)],
        )

    def delete_memory_version(self, memory_id: UUID, version: int) -> None:
        """Delete a specific version of a memory."""
        self._execute(
            "DELETE FROM memory_version WHERE memory_id = :memory_id AND version = :version",
            [
                self._param("memory_id", memory_id),
                self._param("version", version),
            ],
        )

    def list_memories(
        self,
        *,
        prefix: str | None = None,
        source: str | None = None,
        limit: int = 200,
    ) -> list[Memory]:
        """List versioned memories with active version populated.

        Optionally filter by name prefix and/or active version source.
        """
        conditions: list[str] = []
        params: list[dict] = []

        if prefix:
            conditions.append("m.name LIKE :prefix")
            params.append(self._param("prefix", prefix + "%"))
        if source:
            conditions.append("mv.source = :source")
            params.append(self._param("source", source))

        where_clause = (" AND " + " AND ".join(conditions)) if conditions else ""
        params.append(self._param("limit", limit))

        response = self._execute(
            f"""SELECT m.id, m.name, m.active_version, m.includes, m.created_at, m.modified_at,
                       mv.id as mv_id, mv.version, mv.read_only, mv.content,
                       mv.source, mv.created_at as mv_created_at
                FROM memory m
                LEFT JOIN memory_version mv
                    ON mv.memory_id = m.id AND mv.version = m.active_version
                WHERE 1=1{where_clause}
                ORDER BY m.name
                LIMIT :limit""",
            params,
        )
        rows = self._rows_to_dicts(response)
        results: list[Memory] = []
        for row in rows:
            mem = Memory(
                id=UUID(row["id"]),
                name=row["name"],
                active_version=row["active_version"],
                created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
                modified_at=datetime.fromisoformat(row["modified_at"]) if row.get("modified_at") else None,
            )
            if row.get("version") is not None:
                mv = MemoryVersion(
                    id=UUID(row["mv_id"]) if row.get("mv_id") else uuid4(),
                    memory_id=mem.id,
                    version=row["version"],
                    read_only=row.get("read_only", False),
                    content=row.get("content", ""),
                    source=row.get("source", "cogent"),
                    created_at=datetime.fromisoformat(row["mv_created_at"]) if row.get("mv_created_at") else None,
                )
                mem.versions[mv.version] = mv
            results.append(mem)
        return results

    def resolve_memory_keys(self, keys: list[str]) -> list[Memory]:
        """Resolve memory keys with ancestor/child init expansion.

        For each key:
        1. Walk up the path collecting ancestor /init names
        2. Include the key itself
        3. Look for children matching key/ prefix that end in /init

        If two memories share the same name, prefer the one whose active
        version source is not 'polis'.
        Sort results by path depth (count of '/' in name).
        """
        if not keys:
            return []

        names_to_fetch: set[str] = set()
        child_prefixes: list[str] = []

        for key in keys:
            key = key.rstrip("/")
            parts = key.strip("/").split("/")

            # Ancestor inits: /a/init, /a/b/init, ...
            for i in range(1, len(parts)):
                names_to_fetch.add("/" + "/".join(parts[:i]) + "/init")

            # The key itself
            names_to_fetch.add(key)

            # Child init prefixes
            child_prefixes.append(key + "/")

        # --- Batch-fetch by exact names ---
        records_by_name: dict[str, Memory] = {}

        if names_to_fetch:
            name_params: list[dict] = []
            placeholders: list[str] = []
            for i, n in enumerate(sorted(names_to_fetch)):
                pname = f"n_{i}"
                name_params.append(self._param(pname, n))
                placeholders.append(f":{pname}")

            in_clause = ", ".join(placeholders)
            response = self._execute(
                f"""SELECT m.id, m.name, m.active_version, m.includes, m.created_at, m.modified_at,
                           mv.id as mv_id, mv.version, mv.read_only, mv.content,
                           mv.source, mv.created_at as mv_created_at
                    FROM memory m
                    LEFT JOIN memory_version mv ON mv.memory_id = m.id
                    WHERE m.name IN ({in_clause})""",
                name_params,
            )
            rows = self._rows_to_dicts(response)
            # Group rows by memory name
            grouped: dict[str, list[dict]] = {}
            for row in rows:
                grouped.setdefault(row["name"], []).append(row)
            for name, group in grouped.items():
                mem = self._memory_from_rows(group)
                if mem:
                    self._merge_memory_by_name(records_by_name, mem)

        # --- Fetch child /init records by prefix ---
        if child_prefixes:
            prefix_conditions: list[str] = []
            prefix_params: list[dict] = []
            for i, cp in enumerate(child_prefixes):
                pname = f"cp_{i}"
                prefix_params.append(self._param(pname, cp + "%"))
                prefix_conditions.append(f"m.name LIKE :{pname}")

            or_clause = " OR ".join(prefix_conditions)
            response = self._execute(
                f"""SELECT m.id, m.name, m.active_version, m.includes, m.created_at, m.modified_at,
                           mv.id as mv_id, mv.version, mv.read_only, mv.content,
                           mv.source, mv.created_at as mv_created_at
                    FROM memory m
                    LEFT JOIN memory_version mv ON mv.memory_id = m.id
                    WHERE ({or_clause}) AND m.name LIKE '%/init'""",
                prefix_params,
            )
            rows = self._rows_to_dicts(response)
            grouped = {}
            for row in rows:
                grouped.setdefault(row["name"], []).append(row)
            for name, group in grouped.items():
                mem = self._memory_from_rows(group)
                if mem:
                    self._merge_memory_by_name(records_by_name, mem)

        return sorted(
            records_by_name.values(),
            key=lambda m: m.name.count("/"),
        )

    @staticmethod
    def _merge_memory_by_name(
        records_by_name: dict[str, Memory],
        mem: Memory,
    ) -> None:
        """Insert mem into records_by_name, preferring non-polis source on collision."""
        existing = records_by_name.get(mem.name)
        if existing is None:
            records_by_name[mem.name] = mem
        else:
            new_active = mem.versions.get(mem.active_version)
            old_active = existing.versions.get(existing.active_version)
            new_source = new_active.source if new_active else "cogent"
            old_source = old_active.source if old_active else "cogent"
            if old_source == "polis" and new_source != "polis":
                records_by_name[mem.name] = mem

    # ═══════════════════════════════════════════════════════════
    # PROGRAMS
    # ═══════════════════════════════════════════════════════════

    def upsert_program(self, program: Program) -> UUID:
        """Insert or update a program by name."""
        response = self._execute(
            """INSERT INTO programs
                   (id, name, memory_id, memory_version,
                    tools, metadata, runner)
               VALUES (:id, :name, :memory_id, :memory_version,
                       :tools::jsonb, :metadata::jsonb, :runner)
               ON CONFLICT (name)
               DO UPDATE SET memory_id = EXCLUDED.memory_id, memory_version = EXCLUDED.memory_version,
                            tools = EXCLUDED.tools, metadata = EXCLUDED.metadata,
                            runner = EXCLUDED.runner,
                            updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", program.id),
                self._param("name", program.name),
                self._param("memory_id", program.memory_id),
                self._param("memory_version", program.memory_version),
                self._param("tools", program.tools),
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
        tools = row.get("tools", [])
        if isinstance(tools, str):
            tools = json.loads(tools)
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        return Program(
            id=UUID(row["id"]),
            name=row["name"],
            memory_id=UUID(row["memory_id"]) if row.get("memory_id") else None,
            memory_version=row.get("memory_version"),
            tools=tools,
            metadata=metadata,
            runner=row.get("runner"),
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None,
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
            program_name=row.get("program_name", "vsm/s1/do-content"),
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
            """INSERT INTO conversations (id, context_key, status,
                                          cli_session_id, metadata)
               VALUES (:id, :context_key, :status, :cli_session_id, :metadata::jsonb)
               ON CONFLICT (id)
               DO UPDATE SET status = EXCLUDED.status, cli_session_id = EXCLUDED.cli_session_id,
                            metadata = EXCLUDED.metadata, last_active = now()
               RETURNING id, started_at, last_active""",
            [
                self._param("id", conv.id),
                self._param("context_key", conv.context_key),
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
                       :status, :tokens_input, :tokens_output, CAST(:cost_usd AS NUMERIC),
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
                      tokens_output = :tokens_output, cost_usd = CAST(:cost_usd AS NUMERIC),
                      duration_ms = :duration_ms, events_emitted = :events_emitted::jsonb,
                      error = :error, model_version = :model_version,
                      completed_at = CAST(:completed_at AS TIMESTAMPTZ)
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
            """INSERT INTO triggers (id, program_name, event_pattern, priority, config, enabled,
                                    throttle_timestamps, throttle_rejected, throttle_active)
               VALUES (:id, :program_name, :event_pattern, :priority, :config::jsonb, :enabled,
                       :throttle_timestamps::jsonb, :throttle_rejected, :throttle_active)
               RETURNING id, created_at""",
            [
                self._param("id", trigger.id),
                self._param("program_name", trigger.program_name),
                self._param("event_pattern", trigger.event_pattern),
                self._param("priority", trigger.priority),
                self._param("config", trigger.config.model_dump()),
                self._param("enabled", trigger.enabled),
                self._param("throttle_timestamps", trigger.throttle_timestamps),
                self._param("throttle_rejected", trigger.throttle_rejected),
                self._param("throttle_active", trigger.throttle_active),
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
        timestamps = row.get("throttle_timestamps", [])
        if isinstance(timestamps, str):
            timestamps = json.loads(timestamps)
        return Trigger(
            id=UUID(row["id"]),
            program_name=row["program_name"],
            event_pattern=row.get("event_pattern", ""),
            priority=row.get("priority", 10),
            config=TriggerConfig(**config) if config else TriggerConfig(),
            enabled=row.get("enabled", True),
            throttle_timestamps=[float(t) for t in timestamps],
            throttle_rejected=row.get("throttle_rejected", 0),
            throttle_active=row.get("throttle_active", False),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def throttle_check(self, trigger_id: UUID, max_events: int, window_seconds: int) -> "ThrottleResult":
        from brain.db.models import ThrottleResult

        if max_events <= 0:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        import time
        now = time.time()
        cutoff = now - window_seconds

        sql = """
            WITH prev AS (
                SELECT throttle_active AS prev_active FROM triggers WHERE id = :id
            ),
            pruned AS (
                SELECT COALESCE(jsonb_agg(t), '[]'::jsonb) AS ts
                FROM jsonb_array_elements_text(
                    (SELECT throttle_timestamps FROM triggers WHERE id = :id)
                ) AS t
                WHERE t::double precision > :cutoff
            ),
            pruned_count AS (
                SELECT jsonb_array_length((SELECT ts FROM pruned)) AS cnt
            )
            UPDATE triggers
            SET
                throttle_timestamps = CASE
                    WHEN (SELECT cnt FROM pruned_count) >= :max_events
                    THEN (SELECT ts FROM pruned)
                    ELSE (SELECT ts FROM pruned) || to_jsonb(:now::text)
                END,
                throttle_rejected = CASE
                    WHEN (SELECT cnt FROM pruned_count) >= :max_events
                    THEN throttle_rejected + 1
                    ELSE throttle_rejected
                END,
                throttle_active = (SELECT cnt FROM pruned_count) >= :max_events
            WHERE id = :id
            RETURNING throttle_active, (SELECT prev_active FROM prev) AS prev_throttle_active
        """
        response = self._execute(sql, [
            self._param("id", trigger_id),
            self._param("cutoff", cutoff),
            self._param("max_events", max_events),
            self._param("now", now),
        ])
        row = self._first_row(response)
        if not row:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        active = row.get("throttle_active", False)
        prev = row.get("prev_throttle_active", False)
        return ThrottleResult(
            allowed=not active,
            state_changed=active != prev,
            throttle_active=active,
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

    def upsert_cron(self, cron: Cron) -> UUID:
        """Insert or update a cron rule, deduplicating by (cron_expression, event_pattern)."""
        existing = self.list_cron(enabled_only=False)
        for ec in existing:
            if ec.cron_expression == cron.cron_expression and ec.event_pattern == cron.event_pattern:
                return ec.id
        return self.insert_cron(cron)

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

    # ═══════════════════════════════════════════════════════════
    # TOOLS
    # ═══════════════════════════════════════════════════════════

    def upsert_tool(self, tool: Tool) -> UUID:
        """Insert or update a tool by name."""
        response = self._execute(
            """INSERT INTO tools
                   (id, name, description, instructions, input_schema, handler,
                    iam_role_arn, enabled, metadata)
               VALUES (:id, :name, :description, :instructions, :input_schema::jsonb,
                       :handler, :iam_role_arn, :enabled, :metadata::jsonb)
               ON CONFLICT (name)
               DO UPDATE SET description = EXCLUDED.description,
                            instructions = EXCLUDED.instructions,
                            input_schema = EXCLUDED.input_schema,
                            handler = EXCLUDED.handler,
                            iam_role_arn = EXCLUDED.iam_role_arn,
                            enabled = EXCLUDED.enabled,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
               RETURNING id, created_at, updated_at""",
            [
                self._param("id", tool.id),
                self._param("name", tool.name),
                self._param("description", tool.description),
                self._param("instructions", tool.instructions),
                self._param("input_schema", tool.input_schema),
                self._param("handler", tool.handler),
                self._param("iam_role_arn", tool.iam_role_arn),
                self._param("enabled", tool.enabled),
                self._param("metadata", tool.metadata),
            ],
        )
        row = self._first_row(response)
        if row:
            tool.created_at = datetime.fromisoformat(row["created_at"])
            tool.updated_at = datetime.fromisoformat(row["updated_at"])
            return UUID(row["id"])
        raise RuntimeError("Failed to upsert tool")

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        response = self._execute(
            "SELECT * FROM tools WHERE name = :name",
            [self._param("name", name)],
        )
        row = self._first_row(response)
        return self._tool_from_row(row) if row else None

    def get_tools(self, names: list[str]) -> list[Tool]:
        """Get enabled tools by a list of names."""
        if not names:
            return []
        params: list[dict] = []
        placeholders: list[str] = []
        for i, n in enumerate(names):
            pname = f"n_{i}"
            params.append(self._param(pname, n))
            placeholders.append(f":{pname}")
        in_clause = ", ".join(placeholders)
        response = self._execute(
            f"SELECT * FROM tools WHERE name IN ({in_clause}) AND enabled = true",
            params,
        )
        return [self._tool_from_row(r) for r in self._rows_to_dicts(response)]

    def list_tools(self, *, prefix: str | None = None, enabled_only: bool = True) -> list[Tool]:
        """List tools, optionally filtering by name prefix and enabled status."""
        clauses: list[str] = []
        params: list[dict] = []
        if prefix is not None:
            clauses.append("name LIKE :prefix")
            params.append(self._param("prefix", prefix + "%"))
        if enabled_only:
            clauses.append("enabled = true")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        response = self._execute(
            f"SELECT * FROM tools{where} ORDER BY name",
            params or None,
        )
        return [self._tool_from_row(r) for r in self._rows_to_dicts(response)]

    def delete_tool(self, name: str) -> bool:
        """Delete a tool by name."""
        response = self._execute(
            "DELETE FROM tools WHERE name = :name",
            [self._param("name", name)],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def update_tool_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a tool by name."""
        response = self._execute(
            "UPDATE tools SET enabled = :enabled, updated_at = now() WHERE name = :name",
            [
                self._param("enabled", enabled),
                self._param("name", name),
            ],
        )
        return response.get("numberOfRecordsUpdated", 0) == 1

    def _tool_from_row(self, row: dict) -> Tool:
        input_schema = row.get("input_schema", {})
        if isinstance(input_schema, str):
            input_schema = json.loads(input_schema)
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Tool(
            id=UUID(row["id"]),
            name=row["name"],
            description=row.get("description", ""),
            instructions=row.get("instructions", ""),
            input_schema=input_schema,
            handler=row.get("handler", ""),
            iam_role_arn=row.get("iam_role_arn"),
            enabled=row.get("enabled", True),
            metadata=metadata,
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None,
        )

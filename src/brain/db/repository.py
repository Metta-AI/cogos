"""Async PostgreSQL repository: CRUD for all 12 tables."""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from brain.db.models import (
    Alert,
    AlertSeverity,
    Budget,
    BudgetPeriod,
    Channel,
    ChannelType,
    Conversation,
    ConversationStatus,
    Event,
    Execution,
    ExecutionStatus,
    MemoryRecord,
    MemoryScope,
    MemoryType,
    Task,
    TaskStatus,
    Trace,
    Trigger,
    TriggerConfig,
    TriggerType,
)

logger = logging.getLogger(__name__)


class Repository:
    """Async database repository wrapping an asyncpg connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str, **kwargs) -> Repository:
        pool = await asyncpg.create_pool(dsn, **kwargs)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(self) -> Repository:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ═══════════════════════════════════════════════════════════
    # EVENTS (append-only log)
    # ═══════════════════════════════════════════════════════════

    async def append_event(self, event: Event) -> int:
        row = await self._pool.fetchrow(
            """INSERT INTO events (cogent_id, event_type, source, payload, parent_event_id)
               VALUES ($1, $2, $3, $4, $5) RETURNING id, created_at""",
            event.cogent_id,
            event.event_type,
            event.source,
            json.dumps(event.payload),
            event.parent_event_id,
        )
        event.id = row["id"]
        event.created_at = row["created_at"]
        return row["id"]

    async def get_events(
        self,
        cogent_id: str,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        if event_type:
            rows = await self._pool.fetch(
                """SELECT id, cogent_id, event_type, source, payload, parent_event_id, created_at
                   FROM events WHERE cogent_id = $1 AND event_type = $2
                   ORDER BY created_at DESC LIMIT $3""",
                cogent_id,
                event_type,
                limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT id, cogent_id, event_type, source, payload, parent_event_id, created_at
                   FROM events WHERE cogent_id = $1
                   ORDER BY created_at DESC LIMIT $2""",
                cogent_id,
                limit,
            )
        return [self._event_from_row(r) for r in rows]

    async def get_event_tree(self, event_id: int) -> list[Event]:
        """Get an event and all its descendants (full causal tree)."""
        rows = await self._pool.fetch(
            """WITH RECURSIVE tree AS (
                 SELECT id, cogent_id, event_type, source, payload, parent_event_id, created_at
                 FROM events WHERE id = $1
                 UNION ALL
                 SELECT e.id, e.cogent_id, e.event_type, e.source, e.payload, e.parent_event_id, e.created_at
                 FROM events e JOIN tree t ON e.parent_event_id = t.id
               )
               SELECT * FROM tree ORDER BY created_at""",
            event_id,
        )
        return [self._event_from_row(r) for r in rows]

    async def get_event_root(self, event_id: int) -> list[Event]:
        """Walk up to the root event, then return the full tree from that root."""
        root_row = await self._pool.fetchrow(
            """WITH RECURSIVE ancestors AS (
                 SELECT id, parent_event_id FROM events WHERE id = $1
                 UNION ALL
                 SELECT e.id, e.parent_event_id
                 FROM events e JOIN ancestors a ON e.id = a.parent_event_id
               )
               SELECT id FROM ancestors WHERE parent_event_id IS NULL""",
            event_id,
        )
        if not root_row:
            return []
        return await self.get_event_tree(root_row["id"])

    def _event_from_row(self, row: asyncpg.Record) -> Event:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return Event(
            id=row["id"],
            cogent_id=row["cogent_id"],
            event_type=row["event_type"],
            source=row.get("source"),
            payload=payload,
            parent_event_id=row.get("parent_event_id"),
            created_at=row["created_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # MEMORY
    # ═══════════════════════════════════════════════════════════

    async def insert_memory(self, mem: MemoryRecord) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO memory (id, cogent_id, scope, type, name, content, provenance)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (cogent_id, scope, name) WHERE name IS NOT NULL
               DO UPDATE SET content = EXCLUDED.content, provenance = EXCLUDED.provenance,
                            type = EXCLUDED.type, updated_at = now()
               RETURNING id, created_at, updated_at""",
            mem.id,
            mem.cogent_id,
            mem.scope.value,
            mem.type.value,
            mem.name,
            mem.content,
            json.dumps(mem.provenance),
        )
        mem.created_at = row["created_at"]
        mem.updated_at = row["updated_at"]
        return row["id"]

    async def get_memory(self, memory_id: UUID) -> MemoryRecord | None:
        row = await self._pool.fetchrow("SELECT * FROM memory WHERE id = $1", memory_id)
        return self._memory_from_row(row) if row else None

    async def query_memory(
        self,
        cogent_id: str,
        *,
        scope: MemoryScope | None = None,
        type: MemoryType | None = None,
        name: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        conditions = ["cogent_id = $1"]
        params: list[Any] = [cogent_id]
        idx = 2

        if scope:
            conditions.append(f"scope = ${idx}")
            params.append(scope.value)
            idx += 1
        if type:
            conditions.append(f"type = ${idx}")
            params.append(type.value)
            idx += 1
        if name:
            conditions.append(f"name = ${idx}")
            params.append(name)
            idx += 1

        conditions.append("TRUE")
        where = " AND ".join(conditions)

        params.append(limit)
        rows = await self._pool.fetch(
            f"SELECT * FROM memory WHERE {where} ORDER BY updated_at DESC LIMIT ${idx}",
            *params,
        )
        return [self._memory_from_row(r) for r in rows]

    async def query_memory_by_prefixes(
        self,
        cogent_id: str,
        prefixes: list[str],
    ) -> list[MemoryRecord]:
        """Fetch memory records matching any of the given name prefixes.

        COGENT-scoped records override POLIS-scoped records with the same name.
        Returns deduplicated results sorted by name.
        """
        if not prefixes:
            return []

        conditions = []
        params: list[Any] = [cogent_id]
        for i, prefix in enumerate(prefixes):
            params.append(prefix + "%")
            conditions.append(f"name LIKE ${i + 2}")

        prefix_filter = " OR ".join(conditions)
        rows = await self._pool.fetch(
            f"""SELECT * FROM memory
                WHERE cogent_id = $1
                  AND ({prefix_filter})
                ORDER BY scope ASC, name ASC""",
            *params,
        )

        seen: dict[str, MemoryRecord] = {}
        for row in rows:
            record = self._memory_from_row(row)
            if record.name and record.name not in seen:
                seen[record.name] = record
        return sorted(seen.values(), key=lambda r: r.name or "")

    async def delete_memory(self, memory_id: UUID) -> bool:
        result = await self._pool.execute("DELETE FROM memory WHERE id = $1", memory_id)
        return result == "DELETE 1"

    def _memory_from_row(self, row: asyncpg.Record) -> MemoryRecord:
        provenance = row.get("provenance", {})
        if isinstance(provenance, str):
            provenance = json.loads(provenance)
        return MemoryRecord(
            id=row["id"],
            cogent_id=row["cogent_id"],
            scope=MemoryScope(row["scope"]),
            type=MemoryType(row["type"]),
            name=row.get("name"),
            content=row.get("content", ""),
            provenance=provenance,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # SKILLS
    # ═══════════════════════════════════════════════════════════

    async def upsert_skill(
        self,
        cogent_id: str,
        name: str,
        *,
        skill_type: str = "markdown",
        source: str = "golden",
        description: str = "",
        content: str = "",
        triggers: list[dict] | None = None,
        resources: dict | None = None,
        sla: dict | None = None,
        enabled: bool = True,
        version: int = 1,
    ) -> None:
        await self._pool.execute(
            """INSERT INTO skills (cogent_id, name, skill_type, source, description, content,
                                   triggers, resources, sla, enabled, version)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
               ON CONFLICT (cogent_id, name)
               DO UPDATE SET skill_type = EXCLUDED.skill_type, source = EXCLUDED.source,
                            description = EXCLUDED.description, content = EXCLUDED.content,
                            triggers = EXCLUDED.triggers, resources = EXCLUDED.resources,
                            sla = EXCLUDED.sla, enabled = EXCLUDED.enabled,
                            version = EXCLUDED.version, updated_at = now()""",
            cogent_id,
            name,
            skill_type,
            source,
            description,
            content,
            json.dumps(triggers or []),
            json.dumps(resources or {}),
            json.dumps(sla or {}),
            enabled,
            version,
        )

    async def list_skills(self, cogent_id: str, *, source: str | None = None) -> list[dict]:
        if source:
            rows = await self._pool.fetch(
                "SELECT * FROM skills WHERE cogent_id = $1 AND source = $2 ORDER BY name",
                cogent_id,
                source,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM skills WHERE cogent_id = $1 ORDER BY name",
                cogent_id,
            )
        return [dict(r) for r in rows]

    async def delete_skill(self, cogent_id: str, name: str) -> bool:
        result = await self._pool.execute(
            "DELETE FROM skills WHERE cogent_id = $1 AND name = $2",
            cogent_id,
            name,
        )
        return result == "DELETE 1"

    # ═══════════════════════════════════════════════════════════
    # CHANNELS
    # ═══════════════════════════════════════════════════════════

    async def upsert_channel(self, channel: Channel) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO channels (id, cogent_id, type, name, external_id, secret_arn, config, enabled)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (cogent_id, type, name)
               DO UPDATE SET external_id = EXCLUDED.external_id, secret_arn = EXCLUDED.secret_arn,
                            config = EXCLUDED.config, enabled = EXCLUDED.enabled
               RETURNING id, created_at""",
            channel.id,
            channel.cogent_id,
            channel.type.value,
            channel.name,
            channel.external_id,
            channel.secret_arn,
            json.dumps(channel.config),
            channel.enabled,
        )
        channel.created_at = row["created_at"]
        return row["id"]

    async def list_channels(self, cogent_id: str) -> list[Channel]:
        rows = await self._pool.fetch(
            "SELECT * FROM channels WHERE cogent_id = $1 ORDER BY type, name",
            cogent_id,
        )
        return [self._channel_from_row(r) for r in rows]

    def _channel_from_row(self, row: asyncpg.Record) -> Channel:
        config = row.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        return Channel(
            id=row["id"],
            cogent_id=row["cogent_id"],
            type=ChannelType(row["type"]),
            name=row["name"],
            external_id=row.get("external_id"),
            secret_arn=row.get("secret_arn"),
            config=config,
            enabled=row["enabled"],
            created_at=row["created_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # TASKS
    # ═══════════════════════════════════════════════════════════

    async def create_task(self, task: Task) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO tasks (id, cogent_id, title, description, status, priority, source,
                                  external_id, metadata, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               RETURNING id, created_at, updated_at""",
            task.id,
            task.cogent_id,
            task.title,
            task.description,
            task.status.value,
            task.priority,
            task.source,
            task.external_id,
            json.dumps(task.metadata),
            task.error,
        )
        task.created_at = row["created_at"]
        task.updated_at = row["updated_at"]
        return row["id"]

    async def get_task(self, task_id: UUID) -> Task | None:
        row = await self._pool.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        return self._task_from_row(row) if row else None

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        error: str | None = None,
    ) -> bool:
        if status == TaskStatus.COMPLETED:
            result = await self._pool.execute(
                """UPDATE tasks SET status = $2, completed_at = now(), updated_at = now()
                   WHERE id = $1""",
                task_id,
                status.value,
            )
        elif error:
            result = await self._pool.execute(
                """UPDATE tasks SET status = $2, error = $3, updated_at = now()
                   WHERE id = $1""",
                task_id,
                status.value,
                error,
            )
        else:
            result = await self._pool.execute(
                "UPDATE tasks SET status = $2, updated_at = now() WHERE id = $1",
                task_id,
                status.value,
            )
        return result == "UPDATE 1"

    async def claim_task(self, cogent_id: str, role: str) -> Task | None:
        """Atomically claim the next approved task (highest priority first)."""
        row = await self._pool.fetchrow(
            """UPDATE tasks SET status = 'in_progress', updated_at = now()
               WHERE id = (
                   SELECT id FROM tasks
                   WHERE cogent_id = $1 AND status = 'approved'
                   ORDER BY priority DESC, created_at ASC
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            cogent_id,
        )
        if row is None:
            return None
        return self._task_from_row(row)

    async def list_tasks(
        self,
        cogent_id: str,
        *,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[Task]:
        if status:
            rows = await self._pool.fetch(
                """SELECT * FROM tasks WHERE cogent_id = $1 AND status = $2
                   ORDER BY priority DESC, created_at DESC LIMIT $3""",
                cogent_id,
                status.value,
                limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM tasks WHERE cogent_id = $1
                   ORDER BY priority DESC, created_at DESC LIMIT $2""",
                cogent_id,
                limit,
            )
        return [self._task_from_row(r) for r in rows]

    def _task_from_row(self, row: asyncpg.Record) -> Task:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Task(
            id=row["id"],
            cogent_id=row["cogent_id"],
            title=row["title"],
            description=row.get("description", ""),
            status=TaskStatus(row["status"]),
            priority=row.get("priority", 0),
            source=row.get("source", "agent"),
            channel_id=row.get("channel_id"),
            external_id=row.get("external_id"),
            metadata=metadata,
            error=row.get("error"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # CONVERSATIONS
    # ═══════════════════════════════════════════════════════════

    async def upsert_conversation(self, conv: Conversation) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO conversations (id, cogent_id, context_key, channel_id, status,
                                          cli_session_id, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (id)
               DO UPDATE SET status = EXCLUDED.status, cli_session_id = EXCLUDED.cli_session_id,
                            metadata = EXCLUDED.metadata, last_active = now()
               RETURNING id, started_at, last_active""",
            conv.id,
            conv.cogent_id,
            conv.context_key,
            conv.channel_id,
            conv.status.value,
            conv.cli_session_id,
            json.dumps(conv.metadata),
        )
        conv.started_at = row["started_at"]
        conv.last_active = row["last_active"]
        return row["id"]

    async def get_conversation_by_context(self, cogent_id: str, context_key: str) -> Conversation | None:
        row = await self._pool.fetchrow(
            """SELECT * FROM conversations
               WHERE cogent_id = $1 AND context_key = $2 AND status != 'closed'
               ORDER BY last_active DESC LIMIT 1""",
            cogent_id,
            context_key,
        )
        return self._conversation_from_row(row) if row else None

    async def list_conversations(
        self,
        cogent_id: str,
        *,
        status: ConversationStatus | None = None,
    ) -> list[Conversation]:
        if status:
            rows = await self._pool.fetch(
                """SELECT * FROM conversations WHERE cogent_id = $1 AND status = $2
                   ORDER BY last_active DESC""",
                cogent_id,
                status.value,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM conversations WHERE cogent_id = $1 ORDER BY last_active DESC",
                cogent_id,
            )
        return [self._conversation_from_row(r) for r in rows]

    async def close_conversation(self, conversation_id: UUID) -> bool:
        result = await self._pool.execute(
            "UPDATE conversations SET status = 'closed' WHERE id = $1",
            conversation_id,
        )
        return result == "UPDATE 1"

    def _conversation_from_row(self, row: asyncpg.Record) -> Conversation:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Conversation(
            id=row["id"],
            cogent_id=row["cogent_id"],
            context_key=row.get("context_key", ""),
            channel_id=row.get("channel_id"),
            status=ConversationStatus(row["status"]),
            cli_session_id=row.get("cli_session_id"),
            started_at=row["started_at"],
            last_active=row["last_active"],
            metadata=metadata,
        )

    # ═══════════════════════════════════════════════════════════
    # EXECUTIONS
    # ═══════════════════════════════════════════════════════════

    async def insert_execution(self, ex: Execution) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO executions (id, cogent_id, skill_name, trigger_id, conversation_id,
                                       status, tokens_input, tokens_output, cost_usd,
                                       duration_ms, events_emitted, error)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               RETURNING id, started_at""",
            ex.id,
            ex.cogent_id,
            ex.skill_name,
            ex.trigger_id,
            ex.conversation_id,
            ex.status.value,
            ex.tokens_input,
            ex.tokens_output,
            ex.cost_usd,
            ex.duration_ms,
            json.dumps(ex.events_emitted),
            ex.error,
        )
        ex.started_at = row["started_at"]
        return row["id"]

    async def update_execution(self, ex: Execution) -> bool:
        result = await self._pool.execute(
            """UPDATE executions SET status = $2, tokens_input = $3, tokens_output = $4,
                      cost_usd = $5, duration_ms = $6, events_emitted = $7, error = $8,
                      completed_at = $9
               WHERE id = $1""",
            ex.id,
            ex.status.value,
            ex.tokens_input,
            ex.tokens_output,
            ex.cost_usd,
            ex.duration_ms,
            json.dumps(ex.events_emitted),
            ex.error,
            ex.completed_at,
        )
        return result == "UPDATE 1"

    async def query_executions(
        self,
        cogent_id: str,
        *,
        skill_name: str | None = None,
        status: ExecutionStatus | None = None,
        limit: int = 50,
    ) -> list[Execution]:
        conditions = ["cogent_id = $1"]
        params: list[Any] = [cogent_id]
        idx = 2

        if skill_name:
            conditions.append(f"skill_name = ${idx}")
            params.append(skill_name)
            idx += 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status.value)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit)

        rows = await self._pool.fetch(
            f"""SELECT * FROM executions WHERE {where}
                ORDER BY started_at DESC LIMIT ${idx}""",
            *params,
        )
        return [self._execution_from_row(r) for r in rows]

    def _execution_from_row(self, row: asyncpg.Record) -> Execution:
        events = row.get("events_emitted", [])
        if isinstance(events, str):
            events = json.loads(events)
        return Execution(
            id=row["id"],
            cogent_id=row["cogent_id"],
            skill_name=row["skill_name"],
            trigger_id=row.get("trigger_id"),
            conversation_id=row.get("conversation_id"),
            status=ExecutionStatus(row["status"]),
            tokens_input=row.get("tokens_input", 0),
            tokens_output=row.get("tokens_output", 0),
            cost_usd=row.get("cost_usd", Decimal("0")),
            duration_ms=row.get("duration_ms"),
            events_emitted=events,
            error=row.get("error"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
        )

    # ═══════════════════════════════════════════════════════════
    # TRACES
    # ═══════════════════════════════════════════════════════════

    async def insert_trace(self, trace: Trace) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO traces (id, execution_id, tool_calls, memory_ops, model_version)
               VALUES ($1, $2, $3, $4, $5) RETURNING id, created_at""",
            trace.id,
            trace.execution_id,
            json.dumps(trace.tool_calls),
            json.dumps(trace.memory_ops),
            trace.model_version,
        )
        trace.created_at = row["created_at"]
        return row["id"]

    async def get_traces(self, execution_id: UUID) -> list[Trace]:
        rows = await self._pool.fetch(
            "SELECT * FROM traces WHERE execution_id = $1 ORDER BY created_at",
            execution_id,
        )
        return [self._trace_from_row(r) for r in rows]

    def _trace_from_row(self, row: asyncpg.Record) -> Trace:
        tool_calls = row.get("tool_calls", [])
        if isinstance(tool_calls, str):
            tool_calls = json.loads(tool_calls)
        memory_ops = row.get("memory_ops", [])
        if isinstance(memory_ops, str):
            memory_ops = json.loads(memory_ops)
        return Trace(
            id=row["id"],
            execution_id=row["execution_id"],
            tool_calls=tool_calls,
            memory_ops=memory_ops,
            model_version=row.get("model_version"),
            created_at=row["created_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # TRIGGERS
    # ═══════════════════════════════════════════════════════════

    async def insert_trigger(self, trigger: Trigger) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO triggers (id, cogent_id, trigger_type, event_pattern, cron_expression,
                                     skill_name, priority, config, enabled)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id, created_at""",
            trigger.id,
            trigger.cogent_id,
            trigger.trigger_type.value,
            trigger.event_pattern,
            trigger.cron_expression,
            trigger.skill_name,
            trigger.priority,
            json.dumps(trigger.config.model_dump()),
            trigger.enabled,
        )
        trigger.created_at = row["created_at"]
        return row["id"]

    async def get_trigger(self, trigger_id: UUID) -> Trigger | None:
        row = await self._pool.fetchrow("SELECT * FROM triggers WHERE id = $1", trigger_id)
        return self._trigger_from_row(row) if row else None

    async def list_triggers(self, cogent_id: str, *, enabled_only: bool = True) -> list[Trigger]:
        if enabled_only:
            rows = await self._pool.fetch(
                "SELECT * FROM triggers WHERE cogent_id = $1 AND enabled = true ORDER BY priority",
                cogent_id,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM triggers WHERE cogent_id = $1 ORDER BY priority",
                cogent_id,
            )
        return [self._trigger_from_row(r) for r in rows]

    async def delete_trigger(self, trigger_id: UUID) -> bool:
        result = await self._pool.execute("DELETE FROM triggers WHERE id = $1", trigger_id)
        return result == "DELETE 1"

    async def update_trigger_config(self, trigger_id: UUID, config: TriggerConfig) -> bool:
        result = await self._pool.execute(
            "UPDATE triggers SET config = $2 WHERE id = $1",
            trigger_id,
            json.dumps(config.model_dump()),
        )
        return result == "UPDATE 1"

    async def update_trigger_enabled(self, trigger_id: UUID, enabled: bool) -> bool:
        result = await self._pool.execute(
            "UPDATE triggers SET enabled = $2 WHERE id = $1",
            trigger_id,
            enabled,
        )
        return result == "UPDATE 1"

    async def notify_trigger_change(self) -> None:
        await self._pool.execute("SELECT pg_notify('trigger_change', '')")

    def _trigger_from_row(self, row: asyncpg.Record) -> Trigger:
        config = row.get("config", {})
        if isinstance(config, str):
            config = json.loads(config)
        return Trigger(
            id=row["id"],
            cogent_id=row["cogent_id"],
            trigger_type=TriggerType(row["trigger_type"]),
            event_pattern=row.get("event_pattern", ""),
            cron_expression=row.get("cron_expression", ""),
            skill_name=row["skill_name"],
            priority=row.get("priority", 10),
            config=TriggerConfig(**config) if config else TriggerConfig(),
            enabled=row.get("enabled", True),
            created_at=row["created_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════

    async def create_alert(self, alert: Alert) -> UUID:
        row = await self._pool.fetchrow(
            """INSERT INTO alerts (id, cogent_id, severity, alert_type, source, message, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id, created_at""",
            alert.id,
            alert.cogent_id,
            alert.severity.value,
            alert.alert_type,
            alert.source,
            alert.message,
            json.dumps(alert.metadata),
        )
        alert.created_at = row["created_at"]
        return row["id"]

    async def get_unresolved_alerts(self, cogent_id: str) -> list[Alert]:
        rows = await self._pool.fetch(
            """SELECT * FROM alerts WHERE cogent_id = $1 AND resolved_at IS NULL
               ORDER BY created_at DESC""",
            cogent_id,
        )
        return [self._alert_from_row(r) for r in rows]

    async def resolve_alert(self, alert_id: UUID) -> bool:
        result = await self._pool.execute(
            "UPDATE alerts SET resolved_at = now() WHERE id = $1",
            alert_id,
        )
        return result == "UPDATE 1"

    def _alert_from_row(self, row: asyncpg.Record) -> Alert:
        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return Alert(
            id=row["id"],
            cogent_id=row["cogent_id"],
            severity=AlertSeverity(row["severity"]),
            alert_type=row["alert_type"],
            source=row["source"],
            message=row["message"],
            metadata=metadata,
            acknowledged_at=row.get("acknowledged_at"),
            resolved_at=row.get("resolved_at"),
            created_at=row["created_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # BUDGET
    # ═══════════════════════════════════════════════════════════

    async def get_or_create_budget(
        self,
        cogent_id: str,
        period: BudgetPeriod,
        period_start: date,
        *,
        token_limit: int = 0,
        cost_limit_usd: Decimal = Decimal("0"),
    ) -> Budget:
        row = await self._pool.fetchrow(
            """INSERT INTO budget (cogent_id, period, period_start, token_limit, cost_limit_usd)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (cogent_id, period, period_start) DO NOTHING
               RETURNING *""",
            cogent_id,
            period.value,
            period_start,
            token_limit,
            cost_limit_usd,
        )
        if row:
            return self._budget_from_row(row)

        row = await self._pool.fetchrow(
            "SELECT * FROM budget WHERE cogent_id = $1 AND period = $2 AND period_start = $3",
            cogent_id,
            period.value,
            period_start,
        )
        return self._budget_from_row(row)

    async def record_spend(
        self,
        cogent_id: str,
        period: BudgetPeriod,
        period_start: date,
        *,
        tokens: int = 0,
        cost_usd: Decimal = Decimal("0"),
    ) -> Budget:
        row = await self._pool.fetchrow(
            """UPDATE budget SET tokens_spent = tokens_spent + $4,
                      cost_spent_usd = cost_spent_usd + $5, updated_at = now()
               WHERE cogent_id = $1 AND period = $2 AND period_start = $3
               RETURNING *""",
            cogent_id,
            period.value,
            period_start,
            tokens,
            cost_usd,
        )
        return self._budget_from_row(row)

    async def check_budget(self, cogent_id: str, period: BudgetPeriod, period_start: date) -> Budget | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM budget WHERE cogent_id = $1 AND period = $2 AND period_start = $3",
            cogent_id,
            period.value,
            period_start,
        )
        return self._budget_from_row(row) if row else None

    def _budget_from_row(self, row: asyncpg.Record) -> Budget:
        return Budget(
            id=row["id"],
            cogent_id=row["cogent_id"],
            period=BudgetPeriod(row["period"]),
            period_start=row["period_start"],
            tokens_spent=row.get("tokens_spent", 0),
            cost_spent_usd=row.get("cost_spent_usd", Decimal("0")),
            token_limit=row.get("token_limit", 0),
            cost_limit_usd=row.get("cost_limit_usd", Decimal("0")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ═══════════════════════════════════════════════════════════
    # LISTEN/NOTIFY
    # ═══════════════════════════════════════════════════════════

    async def listen(self, channel: str, callback) -> None:
        conn = await self._pool.acquire()
        await conn.add_listener(channel, callback)

    async def unlisten(self, channel: str, callback) -> None:
        conn = await self._pool.acquire()
        await conn.remove_listener(channel, callback)

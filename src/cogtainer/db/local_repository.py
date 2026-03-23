"""In-memory repository with JSON file persistence for local development."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from cogtainer.db.models import (
    Alert,
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
    ResourceUsage,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    ThrottleResult,
    Tool,
    Trace,
    Trigger,
)
from cogtainer.db.repository import Repository

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


class LocalRepository(Repository):
    """In-memory repository backed by a JSON file for persistence."""

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            data_dir = str(Path.home() / ".cogos" / "local")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "data.json"
        self._file_mtime: float = 0.0

        self._programs: dict[str, Program] = {}
        self._tasks: dict[UUID, Task] = {}
        self._triggers: dict[UUID, Trigger] = {}
        self._crons: dict[UUID, Cron] = {}
        self._events: list[Event] = []
        self._event_seq: int = 0
        self._runs: dict[UUID, Run] = {}
        self._conversations: dict[UUID, Conversation] = {}
        self._alerts: dict[UUID, Alert] = {}
        self._traces: dict[UUID, Trace] = {}
        self._resources: dict[str, Resource] = {}
        self._resource_usage: list[ResourceUsage] = []

        self._tools: dict[str, Tool] = {}
        self._budgets: dict[tuple[str, str], Budget] = {}
        self._resource_usage_seq: int = 0

        # Versioned memory (v2)
        self._memories: dict[UUID, Memory] = {}  # keyed by memory.id
        self._memory_versions: dict[UUID, list[MemoryVersion]] = {}  # keyed by memory_id

        self._load()

    # ── Persistence ──────────────────────────────────────────

    def _maybe_reload(self) -> None:
        """Reload from disk if the file was modified externally."""
        if not self._file.exists():
            return
        try:
            mtime = self._file.stat().st_mtime
        except OSError:
            return
        if mtime > self._file_mtime:
            self._load()

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            self._file_mtime = self._file.stat().st_mtime
            data = json.loads(self._file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not load local data from %s", self._file)
            return

        # Clear existing state before loading
        self._programs.clear()
        self._tasks.clear()
        self._triggers.clear()
        self._crons.clear()
        self._events.clear()
        self._runs.clear()
        self._conversations.clear()
        self._alerts.clear()
        self._traces.clear()
        self._resources.clear()
        self._resource_usage.clear()
        self._tools.clear()
        self._memories.clear()
        self._memory_versions.clear()

        for p in data.get("programs", []):
            prog = Program(**p)
            self._programs[prog.name] = prog
        for t in data.get("tasks", []):
            task = Task(**t)
            self._tasks[task.id] = task
        for t in data.get("triggers", []):
            trig = Trigger(**t)
            self._triggers[trig.id] = trig
        for c in data.get("crons", []):
            cr = Cron(**c)
            self._crons[cr.id] = cr
        for e in data.get("events", []):
            ev = Event(**e)
            self._events.append(ev)
        self._event_seq = data.get("event_seq", len(self._events))
        for r in data.get("runs", []):
            run = Run(**r)
            self._runs[run.id] = run
        for c in data.get("conversations", []):
            conv = Conversation(**c)
            self._conversations[conv.id] = conv
        for a in data.get("alerts", []):
            alert = Alert(**a)
            self._alerts[alert.id] = alert
        for t in data.get("traces", []):
            tr = Trace(**t)
            self._traces[tr.id] = tr
        for r in data.get("resources", []):
            res = Resource(**r)
            self._resources[res.name] = res
        for u in data.get("resource_usage", []):
            self._resource_usage.append(ResourceUsage(**u))
        for t in data.get("tools", []):
            tool = Tool(**t)
            self._tools[tool.name] = tool

        # Versioned memory (v2)
        for m in data.get("memories_v2", []):
            mem = Memory(**{k: v for k, v in m.items() if k != "versions"})
            self._memories[mem.id] = mem
        for mv in data.get("memory_versions", []):
            ver = MemoryVersion(**mv)
            self._memory_versions.setdefault(ver.memory_id, []).append(ver)

        logger.info(
            "Loaded local data: %d programs, %d tasks, %d events",
            len(self._programs),
            len(self._tasks),
            len(self._events),
        )

    def _save(self) -> None:
        data = {
            "programs": [p.model_dump(mode="json") for p in self._programs.values()],
            "tasks": [t.model_dump(mode="json") for t in self._tasks.values()],
            "triggers": [t.model_dump(mode="json") for t in self._triggers.values()],
            "crons": [c.model_dump(mode="json") for c in self._crons.values()],
            "events": [e.model_dump(mode="json") for e in self._events],
            "event_seq": self._event_seq,
            "runs": [r.model_dump(mode="json") for r in self._runs.values()],
            "conversations": [c.model_dump(mode="json") for c in self._conversations.values()],
            "alerts": [a.model_dump(mode="json") for a in self._alerts.values()],
            "traces": [t.model_dump(mode="json") for t in self._traces.values()],
            "resources": [r.model_dump(mode="json") for r in self._resources.values()],
            "resource_usage": [u.model_dump(mode="json") for u in self._resource_usage],
            "tools": [t.model_dump(mode="json") for t in self._tools.values()],
            "memories_v2": [m.model_dump(mode="json", exclude={"versions"}) for m in self._memories.values()],
            "memory_versions": [
                mv.model_dump(mode="json") for versions in self._memory_versions.values() for mv in versions
            ],
        }
        self._file.write_text(json.dumps(data, indent=2, default=_json_serial))
        self._file_mtime = self._file.stat().st_mtime

    # ── Raw query stubs (not used when routers use typed methods) ─

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return []

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict | None:
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return 0

    # ── Programs ─────────────────────────────────────────────

    def upsert_program(self, program: Program) -> UUID:
        now = datetime.now(UTC)
        if program.name in self._programs:
            existing = self._programs[program.name]
            program.id = existing.id
            program.created_at = existing.created_at
        else:
            program.created_at = now
        program.updated_at = now
        self._programs[program.name] = program
        self._save()
        return program.id

    def get_program(self, name: str) -> Program | None:
        self._maybe_reload()
        return self._programs.get(name)

    def list_programs(self) -> list[Program]:
        self._maybe_reload()
        return list(self._programs.values())

    def delete_program(self, name: str) -> bool:
        if name in self._programs:
            del self._programs[name]
            self._save()
            return True
        return False

    # ── Tasks ────────────────────────────────────────────────

    def create_task(self, task: Task) -> UUID:
        now = datetime.now(UTC)
        task.created_at = now
        task.updated_at = now
        self._tasks[task.id] = task
        self._save()
        return task.id

    def get_task(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)

    def update_task_status(self, task_id: UUID, status: TaskStatus) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = status
        task.updated_at = datetime.now(UTC)
        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(UTC)
        self._save()
        return True

    def update_task(self, task: Task) -> bool:
        if task.id not in self._tasks:
            return False
        task.updated_at = datetime.now(UTC)
        self._tasks[task.id] = task
        self._save()
        return True

    def delete_task(self, task_id: UUID) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save()
            return True
        return False

    def list_tasks(self, *, status: TaskStatus | None = None, limit: int = 100) -> list[Task]:
        self._maybe_reload()
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.created_at or datetime.min, reverse=True)
        return tasks[:limit]

    # ── Triggers ─────────────────────────────────────────────

    def insert_trigger(self, trigger: Trigger) -> UUID:
        trigger.created_at = datetime.now(UTC)
        self._triggers[trigger.id] = trigger
        self._save()
        return trigger.id

    def get_trigger(self, trigger_id: UUID) -> Trigger | None:
        return self._triggers.get(trigger_id)

    def list_triggers(self, *, enabled_only: bool = True, program_name: str | None = None) -> list[Trigger]:
        self._maybe_reload()
        triggers = list(self._triggers.values())
        if enabled_only:
            triggers = [t for t in triggers if t.enabled]
        if program_name:
            triggers = [t for t in triggers if t.program_name == program_name]
        triggers.sort(key=lambda t: t.priority)
        return triggers

    def delete_trigger(self, trigger_id: UUID) -> bool:
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            self._save()
            return True
        return False

    def update_trigger_enabled(self, trigger_id: UUID, enabled: bool) -> bool:
        trigger = self._triggers.get(trigger_id)
        if not trigger:
            return False
        trigger.enabled = enabled
        self._save()
        return True

    def throttle_check(self, trigger_id: UUID, max_events: int, window_seconds: int) -> "ThrottleResult":
        from cogtainer.db.models import ThrottleResult

        trigger = self._triggers.get(trigger_id)
        if not trigger:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        if max_events <= 0:
            return ThrottleResult(allowed=True, state_changed=False, throttle_active=False)

        now = time.time()
        cutoff = now - window_seconds
        prev_active = trigger.throttle_active

        # Prune expired timestamps
        trigger.throttle_timestamps = [ts for ts in trigger.throttle_timestamps if ts > cutoff]

        if len(trigger.throttle_timestamps) >= max_events:
            # Reject
            trigger.throttle_rejected += 1
            trigger.throttle_active = True
            self._save()
            return ThrottleResult(
                allowed=False,
                state_changed=prev_active != trigger.throttle_active,
                throttle_active=True,
            )

        # Allow
        trigger.throttle_timestamps.append(now)
        trigger.throttle_active = False
        self._save()
        return ThrottleResult(
            allowed=True,
            state_changed=prev_active != trigger.throttle_active,
            throttle_active=False,
        )

    # ── Cron ─────────────────────────────────────────────────

    def insert_cron(self, cron: Cron) -> UUID:
        cron.created_at = datetime.now(UTC)
        self._crons[cron.id] = cron
        self._save()
        return cron.id

    def list_cron(self, *, enabled_only: bool = False) -> list[Cron]:
        crons = list(self._crons.values())
        if enabled_only:
            crons = [c for c in crons if c.enabled]
        return crons

    def delete_cron(self, cron_id: UUID) -> bool:
        if cron_id in self._crons:
            del self._crons[cron_id]
            self._save()
            return True
        return False

    def update_cron_enabled(self, cron_id: UUID, enabled: bool) -> bool:
        cron = self._crons.get(cron_id)
        if not cron:
            return False
        cron.enabled = enabled
        self._save()
        return True

    def upsert_cron(self, cron: Cron) -> UUID:
        for ec in self._crons.values():
            if ec.cron_expression == cron.cron_expression and ec.event_pattern == cron.event_pattern:
                return ec.id
        return self.insert_cron(cron)

    # ── Events ───────────────────────────────────────────────

    def append_event(self, event: Event, *, status: str = "sent") -> int:
        self._event_seq += 1
        event.id = self._event_seq
        event.status = status
        event.created_at = datetime.now(UTC)
        self._events.append(event)
        self._save()
        return event.id

    def get_events(self, *, event_type: str | None = None, limit: int = 100) -> list[Event]:
        self._maybe_reload()
        events = list(reversed(self._events))
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[:limit]

    def get_event_tree(self, event_id: int) -> list[Event]:
        by_id = {e.id: e for e in self._events}
        if event_id not in by_id:
            return []
        result = []
        queue = [event_id]
        while queue:
            eid = queue.pop(0)
            if eid in by_id:
                result.append(by_id[eid])
                for e in self._events:
                    if e.parent_event_id == eid and e.id is not None:
                        queue.append(e.id)
        result.sort(key=lambda e: e.created_at or datetime.min)
        return result

    def get_event_root(self, event_id: int) -> list[Event]:
        by_id = {e.id: e for e in self._events}
        current = by_id.get(event_id)
        if not current:
            return []
        while current.parent_event_id and current.parent_event_id in by_id:
            current = by_id[current.parent_event_id]
        assert current.id is not None
        return self.get_event_tree(current.id)

    def get_proposed_events(self, *, limit: int = 50) -> list[Event]:
        return [e for e in self._events if e.status == "proposed"][:limit]

    def mark_event_sent(self, event_id: int) -> bool:
        for e in self._events:
            if e.id == event_id:
                e.status = "sent"
                self._save()
                return True
        return False

    # ── Runs ─────────────────────────────────────────────────

    def insert_run(self, run: Run) -> UUID:
        run.started_at = run.started_at or datetime.now(UTC)
        self._runs[run.id] = run
        self._save()
        return run.id

    def update_run(self, run: Run) -> bool:
        if run.id not in self._runs:
            return False
        self._runs[run.id] = run
        self._save()
        return True

    def query_runs(
        self,
        *,
        program_name: str | None = None,
        conversation_id: UUID | None = None,
        task_id: UUID | None = None,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> list[Run]:
        self._maybe_reload()
        runs = list(self._runs.values())
        if program_name:
            runs = [r for r in runs if r.program_name == program_name]
        if conversation_id:
            runs = [r for r in runs if r.conversation_id == conversation_id]
        if task_id:
            runs = [r for r in runs if r.task_id == task_id]
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.started_at or datetime.min, reverse=True)
        return runs[:limit]

    # ── Conversations ────────────────────────────────────────

    def upsert_conversation(self, conv: Conversation) -> UUID:
        now = datetime.now(UTC)
        if conv.id in self._conversations:
            existing = self._conversations[conv.id]
            conv.started_at = existing.started_at
        else:
            conv.started_at = now
        conv.last_active = now
        self._conversations[conv.id] = conv
        self._save()
        return conv.id

    def get_conversation_by_context(self, context_key: str) -> Conversation | None:
        for c in self._conversations.values():
            if c.context_key == context_key:
                return c
        return None

    def list_conversations(
        self,
        *,
        status: ConversationStatus | None = None,
        limit: int = 100,
    ) -> list[Conversation]:
        self._maybe_reload()
        convs = list(self._conversations.values())
        if status:
            convs = [c for c in convs if c.status == status]
        convs.sort(key=lambda c: c.last_active or datetime.min, reverse=True)
        return convs[:limit]

    def close_conversation(self, conversation_id: UUID) -> bool:
        conv = self._conversations.get(conversation_id)
        if not conv:
            return False
        conv.status = ConversationStatus.CLOSED
        self._save()
        return True

    # ── Alerts ───────────────────────────────────────────────

    def create_alert(self, alert: Alert) -> UUID:
        alert.created_at = datetime.now(UTC)
        self._alerts[alert.id] = alert
        self._save()
        return alert.id

    def get_unresolved_alerts(self) -> list[Alert]:
        self._maybe_reload()
        return [a for a in self._alerts.values() if a.resolved_at is None]

    def resolve_alert(self, alert_id: UUID) -> bool:
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        alert.resolved_at = datetime.now(UTC)
        self._save()
        return True

    def resolve_all_alerts(self) -> int:
        count = 0
        now = datetime.now(UTC)
        for alert in self._alerts.values():
            if alert.resolved_at is None:
                alert.resolved_at = now
                count += 1
        if count:
            self._save()
        return count

    def get_resolved_alerts(self, limit: int = 25) -> list[Alert]:
        self._maybe_reload()
        resolved = [a for a in self._alerts.values() if a.resolved_at is not None]
        resolved.sort(key=lambda a: a.resolved_at or datetime.min, reverse=True)
        return resolved[:limit]

    def delete_alert(self, alert_id: UUID) -> bool:
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            self._save()
            return True
        return False

    # ── Budget ───────────────────────────────────────────────

    def get_or_create_budget(
        self,
        period: BudgetPeriod,
        period_start: date,
        *,
        token_limit: int = 0,
        cost_limit_usd: Decimal = Decimal("0"),
    ) -> Budget:
        key = (period.value, period_start.isoformat())
        if key not in self._budgets:
            self._budgets[key] = Budget(
                period=period,
                period_start=period_start,
                token_limit=token_limit,
                cost_limit_usd=cost_limit_usd,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        return self._budgets[key]

    def record_spend(
        self,
        period: BudgetPeriod,
        period_start: date,
        *,
        tokens: int = 0,
        cost_usd: Decimal = Decimal("0"),
    ) -> Budget:
        budget = self.get_or_create_budget(period, period_start)
        budget.tokens_spent += tokens
        budget.cost_spent_usd += cost_usd
        budget.updated_at = datetime.now(UTC)
        return budget

    def check_budget(self, period: BudgetPeriod, period_start: date) -> Budget | None:
        key = (period.value, period_start.isoformat())
        return self._budgets.get(key)

    # ── Traces ───────────────────────────────────────────────

    def insert_trace(self, trace: Trace) -> UUID:
        trace.created_at = datetime.now(UTC)
        self._traces[trace.id] = trace
        self._save()
        return trace.id

    def get_traces(self, run_id: UUID) -> list[Trace]:
        return [t for t in self._traces.values() if t.run_id == run_id]

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, resource: Resource) -> str:
        self._resources[resource.name] = resource
        self._save()
        return resource.name

    def list_resources(self) -> list[Resource]:
        self._maybe_reload()
        return list(self._resources.values())

    def get_resource(self, name: str) -> Resource | None:
        self._maybe_reload()
        return self._resources.get(name)

    def delete_resource(self, name: str) -> bool:
        if name in self._resources:
            del self._resources[name]
            self._save()
            return True
        return False

    def insert_resource_usage(self, usage: ResourceUsage) -> int:
        self._resource_usage_seq += 1
        usage.id = self._resource_usage_seq
        usage.created_at = datetime.now(UTC)
        self._resource_usage.append(usage)
        self._save()
        return usage.id

    def get_pool_usage(self, resource_name: str) -> int:
        """Count running tasks that consume this pool resource."""
        return sum(
            1
            for t in self._tasks.values()
            if t.status == TaskStatus.RUNNING
            and (
                t.runner == resource_name or resource_name == "concurrent-tasks" or resource_name in (t.resources or [])
            )
        )

    def get_consumable_usage(self, resource_name: str) -> float:
        return sum(u.amount for u in self._resource_usage if u.resource_name == resource_name)

    # ── Tasks (extended) ─────────────────────────────────────

    def get_task_by_name(self, name: str) -> Task | None:
        self._maybe_reload()
        for t in self._tasks.values():
            if t.name == name:
                return t
        return None

    def upsert_task(self, task: Task, *, update_priority: bool = False) -> UUID:
        now = datetime.now(UTC)
        existing = self.get_task_by_name(task.name)
        if existing:
            task.id = existing.id
            task.created_at = existing.created_at
            if not update_priority:
                task.priority = existing.priority
        else:
            task.created_at = now
        task.updated_at = now
        self._tasks[task.id] = task
        self._save()
        return task.id

    # ── Tools ────────────────────────────────────────────────

    def upsert_tool(self, tool: Tool) -> UUID:
        now = datetime.now(UTC)
        if tool.name in self._tools:
            existing = self._tools[tool.name]
            tool.id = existing.id
            tool.created_at = existing.created_at
        else:
            tool.created_at = now
        tool.updated_at = now
        self._tools[tool.name] = tool
        self._save()
        return tool.id

    def get_tool(self, name: str) -> Tool | None:
        self._maybe_reload()
        return self._tools.get(name)

    def get_tools(self, names: list[str]) -> list[Tool]:
        self._maybe_reload()
        return [self._tools[n] for n in names if n in self._tools and self._tools[n].enabled]

    def list_tools(self, *, prefix: str | None = None, enabled_only: bool = True) -> list[Tool]:
        self._maybe_reload()
        tools = list(self._tools.values())
        if prefix is not None:
            tools = [t for t in tools if t.name.startswith(prefix)]
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        tools.sort(key=lambda t: t.name)
        return tools

    def delete_tool(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            self._save()
            return True
        return False

    def update_tool_enabled(self, name: str, enabled: bool) -> bool:
        tool = self._tools.get(name)
        if not tool:
            return False
        tool.enabled = enabled
        tool.updated_at = datetime.now(UTC)
        self._save()
        return True

    # ── Memory (versioned) ──────────────────────────────────

    def insert_memory(self, mem: Memory) -> UUID:
        now = datetime.now(UTC)
        mem.created_at = mem.created_at or now
        mem.modified_at = now
        # Extract any inline versions into _memory_versions storage
        for mv in mem.versions.values():
            mv.created_at = mv.created_at or now
            self._memory_versions.setdefault(mem.id, []).append(mv)
        self._memories[mem.id] = mem
        self._save()
        return mem.id

    def get_memory_by_name(self, name: str) -> Memory | None:
        """Returns Memory with ALL versions populated in versions dict."""
        self._maybe_reload()
        for mem in self._memories.values():
            if mem.name == name:
                # Populate versions dict
                mem.versions = {}
                for mv in self._memory_versions.get(mem.id, []):
                    mem.versions[mv.version] = mv
                return mem
        return None

    def get_memory_by_id(self, memory_id: UUID) -> Memory | None:
        """Returns Memory by ID with ALL versions populated."""
        self._maybe_reload()
        mem = self._memories.get(memory_id)
        if mem is None:
            return None
        mem.versions = {}
        for mv in self._memory_versions.get(mem.id, []):
            mem.versions[mv.version] = mv
        return mem

    def insert_memory_version(self, mv: MemoryVersion) -> None:
        mv.created_at = mv.created_at or datetime.now(UTC)
        self._memory_versions.setdefault(mv.memory_id, []).append(mv)
        # Update modified_at on parent memory
        if mv.memory_id in self._memories:
            self._memories[mv.memory_id].modified_at = datetime.now(UTC)
        self._save()

    def get_memory_version(self, memory_id: UUID, version: int) -> MemoryVersion | None:
        for mv in self._memory_versions.get(memory_id, []):
            if mv.version == version:
                return mv
        return None

    def get_max_version(self, memory_id: UUID) -> int:
        versions = self._memory_versions.get(memory_id, [])
        if not versions:
            return 0
        return max(mv.version for mv in versions)

    def list_memory_versions(self, memory_id: UUID) -> list[MemoryVersion]:
        versions = list(self._memory_versions.get(memory_id, []))
        versions.sort(key=lambda mv: mv.version)
        return versions

    def update_active_version(self, memory_id: UUID, version: int) -> None:
        mem = self._memories.get(memory_id)
        if mem:
            mem.active_version = version
            mem.modified_at = datetime.now(UTC)
            self._save()

    def update_version_read_only(self, memory_id: UUID, version: int, read_only: bool) -> None:
        for mv in self._memory_versions.get(memory_id, []):
            if mv.version == version:
                mv.read_only = read_only
                self._save()
                return

    def update_memory_includes(self, memory_id: UUID, includes: list[str]) -> None:
        mem = self._memories.get(memory_id)
        if mem:
            mem.includes = includes
            mem.modified_at = datetime.now(UTC)
            self._save()

    def update_memory_name(self, memory_id: UUID, new_name: str) -> None:
        mem = self._memories.get(memory_id)
        if mem:
            mem.name = new_name
            mem.modified_at = datetime.now(UTC)
            self._save()

    def delete_memory(self, memory_id: UUID) -> None:
        """Deletes memory AND all its versions."""
        self._memories.pop(memory_id, None)
        self._memory_versions.pop(memory_id, None)
        self._save()

    def delete_memory_version(self, memory_id: UUID, version: int) -> None:
        versions = self._memory_versions.get(memory_id, [])
        self._memory_versions[memory_id] = [mv for mv in versions if mv.version != version]
        self._save()

    def list_memories(
        self,
        *,
        prefix: str | None = None,
        source: str | None = None,
        limit: int = 200,
    ) -> list[Memory]:
        """List memories, optionally filtering by name prefix and active version source.

        Returns Memory objects with all versions populated.
        """
        self._maybe_reload()
        results: list[Memory] = []
        for mem in self._memories.values():
            if prefix and not mem.name.startswith(prefix):
                continue
            # Check active version source for filtering
            active_mv = self.get_memory_version(mem.id, mem.active_version)
            if source and (active_mv is None or active_mv.source != source):
                continue
            # Populate all versions
            mem.versions = {}
            for mv in self._memory_versions.get(mem.id, []):
                mem.versions[mv.version] = mv
            results.append(mem)
        results.sort(key=lambda m: m.name)
        return results[:limit]

    def resolve_memory_keys(self, keys: list[str]) -> list[Memory]:
        """Resolve memory keys with ancestor/child init expansion.

        For each key:
        1. Walk up the path collecting ancestor /init names
        2. Include the key itself
        3. Look for children matching key/ prefix that end in /init

        If two memories have the same name, keep the one with source != 'cogtainer'.
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

        # Collect matching memories by name
        # If duplicate names, prefer non-cogtainer source
        records_by_name: dict[str, Memory] = {}

        for mem in self._memories.values():
            matched = False
            if mem.name in names_to_fetch:
                matched = True
            else:
                for cp in child_prefixes:
                    if mem.name.startswith(cp) and mem.name.endswith("/init"):
                        matched = True
                        break

            if not matched:
                continue

            # Populate versions
            mem_copy = mem.model_copy()
            mem_copy.versions = {}
            for mv in self._memory_versions.get(mem.id, []):
                mem_copy.versions[mv.version] = mv

            existing = records_by_name.get(mem.name)
            if existing is None:
                records_by_name[mem.name] = mem_copy
            else:
                # Prefer non-cogtainer: check active version source
                new_active = mem_copy.versions.get(mem_copy.active_version)
                old_active = existing.versions.get(existing.active_version)
                new_source = new_active.source if new_active else "cogent"
                old_source = old_active.source if old_active else "cogent"
                if old_source == "cogtainer" and new_source != "cogtainer":
                    records_by_name[mem.name] = mem_copy

        return sorted(
            records_by_name.values(),
            key=lambda m: m.name.count("/"),
        )

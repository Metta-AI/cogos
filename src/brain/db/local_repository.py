"""In-memory repository with JSON file persistence for local development."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from brain.db.models import (
    Alert,
    AlertSeverity,
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
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Trace,
    Trigger,
    TriggerConfig,
)

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


class LocalRepository:
    """In-memory repository backed by a JSON file for persistence."""

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            data_dir = os.environ.get("COGENT_LOCAL_DATA", str(Path.home() / ".cogent" / "local"))
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
        self._channels: dict[UUID, Channel] = {}
        self._alerts: dict[UUID, Alert] = {}
        self._memory: dict[UUID, MemoryRecord] = {}
        self._traces: dict[UUID, Trace] = {}

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
        self._channels.clear()
        self._alerts.clear()
        self._memory.clear()
        self._traces.clear()

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
        for ch in data.get("channels", []):
            chan = Channel(**ch)
            self._channels[chan.id] = chan
        for a in data.get("alerts", []):
            alert = Alert(**a)
            self._alerts[alert.id] = alert
        for m in data.get("memory", []):
            mem = MemoryRecord(**m)
            self._memory[mem.id] = mem
        for t in data.get("traces", []):
            tr = Trace(**t)
            self._traces[tr.id] = tr

        logger.info("Loaded local data: %d programs, %d tasks, %d events",
                     len(self._programs), len(self._tasks), len(self._events))

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
            "channels": [ch.model_dump(mode="json") for ch in self._channels.values()],
            "alerts": [a.model_dump(mode="json") for a in self._alerts.values()],
            "memory": [m.model_dump(mode="json") for m in self._memory.values()],
            "traces": [t.model_dump(mode="json") for t in self._traces.values()],
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
        now = datetime.utcnow()
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
        now = datetime.utcnow()
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
        task.updated_at = datetime.utcnow()
        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.utcnow()
        self._save()
        return True

    def update_task(self, task: Task) -> bool:
        if task.id not in self._tasks:
            return False
        task.updated_at = datetime.utcnow()
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
        trigger.created_at = datetime.utcnow()
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

    # ── Cron ─────────────────────────────────────────────────

    def insert_cron(self, cron: Cron) -> UUID:
        cron.created_at = datetime.utcnow()
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

    # ── Events ───────────────────────────────────────────────

    def append_event(self, event: Event) -> int:
        self._event_seq += 1
        event.id = self._event_seq
        event.created_at = datetime.utcnow()
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
                    if e.parent_event_id == eid:
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
        return self.get_event_tree(current.id)

    # ── Runs ─────────────────────────────────────────────────

    def insert_run(self, run: Run) -> UUID:
        run.started_at = run.started_at or datetime.utcnow()
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
        now = datetime.utcnow()
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

    # ── Channels ─────────────────────────────────────────────

    def upsert_channel(self, channel: Channel) -> UUID:
        channel.created_at = channel.created_at or datetime.utcnow()
        self._channels[channel.id] = channel
        self._save()
        return channel.id

    def list_channels(self) -> list[Channel]:
        self._maybe_reload()
        return sorted(self._channels.values(), key=lambda c: c.name)

    def delete_channel(self, name: str) -> bool:
        """Delete a channel by name. Returns True if found and deleted."""
        target_id = None
        for cid, ch in self._channels.items():
            if ch.name == name:
                target_id = cid
                break
        if target_id is None:
            return False
        del self._channels[target_id]
        self._save()
        return True

    # ── Alerts ───────────────────────────────────────────────

    def create_alert(self, alert: Alert) -> UUID:
        alert.created_at = datetime.utcnow()
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
        alert.resolved_at = datetime.utcnow()
        self._save()
        return True

    def resolve_all_alerts(self) -> int:
        count = 0
        now = datetime.utcnow()
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

    # ── Memory ───────────────────────────────────────────────

    def insert_memory(self, mem: MemoryRecord) -> UUID:
        now = datetime.utcnow()
        mem.created_at = now
        mem.updated_at = now
        self._memory[mem.id] = mem
        self._save()
        return mem.id

    def get_memory(self, memory_id: UUID) -> MemoryRecord | None:
        return self._memory.get(memory_id)

    def query_memory(
        self,
        *,
        scope: MemoryScope | None = None,
        name_prefix: str | None = None,
        limit: int = 200,
    ) -> list[MemoryRecord]:
        self._maybe_reload()
        records = list(self._memory.values())
        if scope:
            records = [m for m in records if m.scope == scope]
        if name_prefix:
            records = [m for m in records if m.name and m.name.startswith(name_prefix)]
        records.sort(key=lambda m: (m.name or "", m.scope.value if m.scope else ""))
        return records[:limit]

    def delete_memory(self, memory_id: UUID) -> bool:
        if memory_id in self._memory:
            del self._memory[memory_id]
            self._save()
            return True
        return False

    # ── Traces ───────────────────────────────────────────────

    def insert_trace(self, trace: Trace) -> UUID:
        trace.created_at = datetime.utcnow()
        self._traces[trace.id] = trace
        self._save()
        return trace.id

    def get_traces(self, run_id: UUID) -> list[Trace]:
        return [t for t in self._traces.values() if t.run_id == run_id]

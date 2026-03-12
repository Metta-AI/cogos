"""In-memory CogOS repository with JSON file persistence for local development."""

from __future__ import annotations

import json
import logging
import os
from fnmatch import fnmatchcase
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from cogos.db.models import (
    Capability,
    Channel,
    ChannelMessage,
    ChannelType,
    Cron,
    DeliveryStatus,
    Event,
    EventDelivery,
    EventOutbox,
    EventOutboxStatus,
    EventType,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessStatus,
    Resource,
    ResourceType,
    Run,
    RunStatus,
    Schema,
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
    """In-memory CogOS repository backed by a JSON file."""

    def __init__(self, data_dir: str | None = None) -> None:
        if data_dir is None:
            data_dir = os.environ.get("COGENT_LOCAL_DATA", str(Path.home() / ".cogent" / "local"))
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "cogos_data.json"
        self._file_mtime: float = 0.0
        self._event_outbox_failed_retry_backoff_seconds = int(
            os.environ.get("COGOS_EVENT_OUTBOX_FAILED_RETRY_BACKOFF_SECONDS", "60"),
        )
        self._event_outbox_failed_max_attempts = int(
            os.environ.get("COGOS_EVENT_OUTBOX_FAILED_MAX_ATTEMPTS", "10"),
        )

        self._processes: dict[UUID, Process] = {}
        self._capabilities: dict[UUID, Capability] = {}
        self._handlers: dict[UUID, Handler] = {}
        self._files: dict[UUID, File] = {}
        self._file_versions: dict[UUID, list[FileVersion]] = {}  # keyed by file_id
        self._process_capabilities: dict[UUID, ProcessCapability] = {}
        self._resources: dict[str, Resource] = {}  # keyed by name
        self._cron_rules: dict[UUID, Cron] = {}
        self._events: list[Event] = []
        self._event_deliveries: dict[UUID, EventDelivery] = {}
        self._event_outbox: dict[UUID, EventOutbox] = {}
        self._runs: dict[UUID, Run] = {}
        self._event_types: dict[str, EventType] = {}  # keyed by name
        self._schemas: dict[UUID, Schema] = {}
        self._channels: dict[UUID, Channel] = {}
        self._channel_messages: dict[UUID, ChannelMessage] = {}
        self._meta: dict[str, dict[str, str]] = {}

        self._load()

    # ── Persistence ──────────────────────────────────────────

    def _maybe_reload(self) -> None:
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
            logger.warning("Could not load cogos data from %s", self._file)
            return

        self._processes.clear()
        self._capabilities.clear()
        self._handlers.clear()
        self._process_capabilities.clear()
        self._resources.clear()
        self._cron_rules.clear()
        self._files.clear()
        self._file_versions.clear()
        self._events.clear()
        self._event_deliveries.clear()
        self._event_outbox.clear()
        self._runs.clear()
        self._event_types.clear()
        self._schemas.clear()
        self._channels.clear()
        self._channel_messages.clear()
        self._meta.clear()

        for p in data.get("processes", []):
            proc = Process(**p)
            self._processes[proc.id] = proc
        for c in data.get("capabilities", []):
            cap = Capability(**c)
            self._capabilities[cap.id] = cap
        for h in data.get("handlers", []):
            handler = Handler(**h)
            self._handlers[handler.id] = handler
        for pc in data.get("process_capabilities", []):
            pcap = ProcessCapability(**pc)
            self._process_capabilities[pcap.id] = pcap
        for res in data.get("resources", []):
            r = Resource(**res)
            self._resources[r.name] = r
        for cr in data.get("cron_rules", []):
            c = Cron(**cr)
            self._cron_rules[c.id] = c
        for f in data.get("files", []):
            fi = File(**f)
            self._files[fi.id] = fi
        for fv in data.get("file_versions", []):
            ver = FileVersion(**fv)
            self._file_versions.setdefault(ver.file_id, []).append(ver)
        for e in data.get("events", []):
            self._events.append(Event(**e))
        for ed in data.get("event_deliveries", []):
            delivery = EventDelivery(**ed)
            self._event_deliveries[delivery.id] = delivery
        for outbox in data.get("event_outbox", []):
            item = EventOutbox(**outbox)
            self._event_outbox[item.id] = item
        for r in data.get("runs", []):
            run = Run(**r)
            self._runs[run.id] = run
        for et in data.get("event_types", []):
            evt = EventType(**et)
            self._event_types[evt.name] = evt
        for s in data.get("schemas", []):
            schema = Schema(**s)
            self._schemas[schema.id] = schema
        for ch in data.get("channels", []):
            channel = Channel(**ch)
            self._channels[channel.id] = channel
        for cm in data.get("channel_messages", []):
            msg = ChannelMessage(**cm)
            self._channel_messages[msg.id] = msg
        self._meta.update(data.get("meta", {}))

        logger.info(
            "Loaded cogos data: %d processes, %d capabilities, %d files, %d events, %d runs",
            len(self._processes), len(self._capabilities), len(self._files),
            len(self._events), len(self._runs),
        )

    def _save(self) -> None:
        data = {
            "processes": [p.model_dump(mode="json") for p in self._processes.values()],
            "capabilities": [c.model_dump(mode="json") for c in self._capabilities.values()],
            "handlers": [h.model_dump(mode="json") for h in self._handlers.values()],
            "process_capabilities": [pc.model_dump(mode="json") for pc in self._process_capabilities.values()],
            "files": [f.model_dump(mode="json") for f in self._files.values()],
            "file_versions": [
                fv.model_dump(mode="json")
                for versions in self._file_versions.values()
                for fv in versions
            ],
            "resources": [r.model_dump(mode="json") for r in self._resources.values()],
            "cron_rules": [c.model_dump(mode="json") for c in self._cron_rules.values()],
            "events": [e.model_dump(mode="json") for e in self._events],
            "event_deliveries": [ed.model_dump(mode="json") for ed in self._event_deliveries.values()],
            "event_outbox": [item.model_dump(mode="json") for item in self._event_outbox.values()],
            "runs": [r.model_dump(mode="json") for r in self._runs.values()],
            "event_types": [et.model_dump(mode="json") for et in self._event_types.values()],
            "schemas": [s.model_dump(mode="json") for s in self._schemas.values()],
            "channels": [ch.model_dump(mode="json") for ch in self._channels.values()],
            "channel_messages": [m.model_dump(mode="json") for m in self._channel_messages.values()],
            "meta": self._meta,
        }
        self._file.write_text(json.dumps(data, indent=2, default=_json_serial))
        self._file_mtime = self._file.stat().st_mtime

    # ── Raw query stubs (used by cogos_events router) ────────

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return 0

    def clear_all(self) -> None:
        """Wipe all in-memory data and persist the empty state."""
        self._processes.clear()
        self._capabilities.clear()
        self._handlers.clear()
        self._files.clear()
        self._file_versions.clear()
        self._process_capabilities.clear()
        self._resources.clear()
        self._cron_rules.clear()
        self._events.clear()
        self._event_deliveries.clear()
        self._event_outbox.clear()
        self._runs.clear()
        self._event_types.clear()
        self._schemas.clear()
        self._channels.clear()
        self._channel_messages.clear()
        self._meta.clear()
        self._save()

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

    # ── Processes ─────────────────────────────────────────────

    def upsert_process(self, p: Process) -> UUID:
        now = datetime.utcnow()
        existing = self._processes.get(p.id)
        if existing is None:
            # Check by name
            for ep in self._processes.values():
                if ep.name == p.name:
                    existing = ep
                    break
        if existing:
            p.id = existing.id
            p.created_at = existing.created_at
        else:
            p.created_at = now
        p.updated_at = now
        self._processes[p.id] = p
        self._save()
        return p.id

    def get_process(self, process_id: UUID) -> Process | None:
        self._maybe_reload()
        return self._processes.get(process_id)

    def get_process_by_name(self, name: str) -> Process | None:
        self._maybe_reload()
        for process in self._processes.values():
            if process.name == name:
                return process
        return None

    def delete_process(self, process_id: UUID) -> bool:
        if process_id in self._processes:
            del self._processes[process_id]
            self._save()
            return True
        return False

    def list_processes(self, *, status: ProcessStatus | None = None, limit: int = 200) -> list[Process]:
        self._maybe_reload()
        procs = list(self._processes.values())
        if status:
            procs = [p for p in procs if p.status == status]
        procs.sort(key=lambda p: p.name)
        return procs[:limit]

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        process = self._processes.get(process_id)
        if process is None:
            return False
        process.status = status
        if status == ProcessStatus.RUNNABLE:
            process.runnable_since = process.runnable_since or datetime.utcnow()
        else:
            process.runnable_since = None
        process.updated_at = datetime.utcnow()
        self._save()
        return True

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        self._maybe_reload()
        runnable = [p for p in self._processes.values() if p.status == ProcessStatus.RUNNABLE]
        runnable.sort(
            key=lambda p: (
                -p.priority,
                p.runnable_since or datetime.max,
                p.name,
            ),
        )
        return runnable[:limit]

    def increment_retry(self, process_id: UUID) -> bool:
        process = self._processes.get(process_id)
        if process is None:
            return False
        process.retry_count += 1
        process.updated_at = datetime.utcnow()
        self._save()
        return True

    # ── Capabilities ─────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID:
        now = datetime.utcnow()
        existing = self._capabilities.get(cap.id)
        if existing is None:
            for ec in self._capabilities.values():
                if ec.name == cap.name:
                    existing = ec
                    break
        if existing:
            cap.id = existing.id
            cap.created_at = existing.created_at
        else:
            cap.created_at = now
        cap.updated_at = now
        self._capabilities[cap.id] = cap
        self._save()
        return cap.id

    def get_capability_by_name(self, name: str) -> Capability | None:
        self._maybe_reload()
        for c in self._capabilities.values():
            if c.name == name:
                return c
        return None

    def list_capabilities(self, *, enabled_only: bool = False) -> list[Capability]:
        self._maybe_reload()
        caps = list(self._capabilities.values())
        if enabled_only:
            caps = [c for c in caps if c.enabled]
        caps.sort(key=lambda c: c.name)
        return caps

    # ── Handlers ─────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID:
        # Upsert by (process, channel) when channel is set,
        # otherwise by (process, event_pattern) to match RDS ON CONFLICT behavior
        for existing in self._handlers.values():
            if h.channel is not None:
                if existing.process == h.process and existing.channel == h.channel:
                    existing.enabled = h.enabled
                    self._save()
                    return existing.id
            elif h.event_pattern is not None:
                if existing.process == h.process and existing.event_pattern == h.event_pattern:
                    existing.enabled = h.enabled
                    self._save()
                    return existing.id
        h.created_at = datetime.utcnow()
        self._handlers[h.id] = h
        self._save()
        return h.id

    def list_handlers(self, *, process_id: UUID | None = None, enabled_only: bool = False) -> list[Handler]:
        self._maybe_reload()
        handlers = list(self._handlers.values())
        if process_id:
            handlers = [h for h in handlers if h.process == process_id]
        if enabled_only:
            handlers = [h for h in handlers if h.enabled]
        handlers.sort(key=lambda h: h.event_pattern or "")
        return handlers

    def delete_handler(self, handler_id: UUID) -> bool:
        if handler_id in self._handlers:
            del self._handlers[handler_id]
            self._save()
            return True
        return False

    def match_handlers(self, event_type: str) -> list[Handler]:
        self._maybe_reload()
        handlers = [
            h for h in self._handlers.values()
            if h.enabled and h.event_pattern is not None and fnmatchcase(event_type, h.event_pattern)
        ]
        handlers.sort(key=lambda h: (str(h.process), h.event_pattern or ""))
        return handlers

    # ── Process Capabilities ────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        """Upsert a process-capability binding by (process, name) pair."""
        for existing in self._process_capabilities.values():
            if existing.process == pc.process and existing.name == pc.name:
                existing.capability = pc.capability
                existing.config = pc.config
                self._save()
                return existing.id
        self._process_capabilities[pc.id] = pc
        self._save()
        return pc.id

    def delete_process_capability(self, pc_id: UUID) -> bool:
        if pc_id in self._process_capabilities:
            del self._process_capabilities[pc_id]
            self._save()
            return True
        return False

    def list_process_capabilities(self, process_id: UUID) -> list[ProcessCapability]:
        self._maybe_reload()
        return [pc for pc in self._process_capabilities.values() if pc.process == process_id]

    def list_processes_for_capability(self, capability_id: UUID) -> list[dict]:
        """Return processes granted a specific capability with grant metadata."""
        self._maybe_reload()
        results = []
        for pc in self._process_capabilities.values():
            if pc.capability == capability_id:
                proc = self._processes.get(pc.process)
                if proc:
                    results.append({
                        "process_id": str(proc.id),
                        "process_name": proc.name,
                        "process_status": proc.status.value if hasattr(proc.status, "value") else str(proc.status),
                        "grant_name": pc.name,
                        "config": pc.config,
                    })
        results.sort(key=lambda r: r["process_name"])
        return results

    def get_capability(self, cap_id: UUID) -> Capability | None:
        self._maybe_reload()
        return self._capabilities.get(cap_id)

    # ── Files ────────────────────────────────────────────────

    def insert_file(self, f: File) -> UUID:
        now = datetime.utcnow()
        f.created_at = now
        f.updated_at = now
        self._files[f.id] = f
        self._save()
        return f.id

    def get_file_by_key(self, key: str) -> File | None:
        self._maybe_reload()
        for f in self._files.values():
            if f.key == key:
                return f
        return None

    def get_file_by_id(self, file_id: UUID) -> File | None:
        self._maybe_reload()
        return self._files.get(file_id)

    def list_files(self, *, prefix: str | None = None, limit: int = 200) -> list[File]:
        self._maybe_reload()
        files = list(self._files.values())
        if prefix:
            files = [f for f in files if f.key.startswith(prefix)]
        files.sort(key=lambda f: f.key)
        return files[:limit]

    def delete_file(self, file_id: UUID) -> bool:
        if file_id in self._files:
            del self._files[file_id]
            self._file_versions.pop(file_id, None)
            self._save()
            return True
        return False

    def insert_file_version(self, fv: FileVersion) -> None:
        fv.created_at = datetime.utcnow()
        self._file_versions.setdefault(fv.file_id, []).append(fv)
        if fv.file_id in self._files:
            self._files[fv.file_id].updated_at = datetime.utcnow()
        self._save()

    def get_active_file_version(self, file_id: UUID) -> FileVersion | None:
        versions = self._file_versions.get(file_id, [])
        active = [v for v in versions if v.is_active]
        return max(active, key=lambda v: v.version) if active else None

    def get_max_file_version(self, file_id: UUID) -> int:
        versions = self._file_versions.get(file_id, [])
        return max((v.version for v in versions), default=0)

    def list_file_versions(self, file_id: UUID) -> list[FileVersion]:
        versions = list(self._file_versions.get(file_id, []))
        versions.sort(key=lambda v: v.version)
        return versions

    def set_active_file_version(self, file_id: UUID, version: int) -> None:
        for fv in self._file_versions.get(file_id, []):
            fv.is_active = fv.version == version
        self._save()

    def delete_file_version(self, file_id: UUID, version: int) -> bool:
        versions = self._file_versions.get(file_id, [])
        before = len(versions)
        self._file_versions[file_id] = [v for v in versions if v.version != version]
        if len(self._file_versions[file_id]) < before:
            self._save()
            return True
        return False

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        for fv in self._file_versions.get(file_id, []):
            if fv.version == version:
                fv.content = content
                self._save()
                return True
        return False

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, r: Resource) -> str:
        now = datetime.utcnow()
        existing = self._resources.get(r.name)
        if existing:
            r.id = existing.id
            r.created_at = existing.created_at
        else:
            r.created_at = now
        self._resources[r.name] = r
        self._save()
        return r.name

    def list_resources(self) -> list[Resource]:
        self._maybe_reload()
        resources = list(self._resources.values())
        resources.sort(key=lambda r: r.name)
        return resources

    # ── Cron Rules ────────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID:
        now = datetime.utcnow()
        # Match by (expression, event_type)
        existing = None
        for ec in self._cron_rules.values():
            if ec.expression == c.expression and ec.event_type == c.event_type:
                existing = ec
                break
        if existing:
            c.id = existing.id
            c.created_at = existing.created_at
        else:
            c.created_at = now
        self._cron_rules[c.id] = c
        self._save()
        return c.id

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        self._maybe_reload()
        rules = list(self._cron_rules.values())
        if enabled_only:
            rules = [c for c in rules if c.enabled]
        rules.sort(key=lambda c: c.expression)
        return rules

    # ── Events ───────────────────────────────────────────────

    def append_event(self, event: Event) -> UUID:
        event.created_at = datetime.utcnow()
        self._events.append(event)
        outbox_item = EventOutbox(
            event=event.id,
            created_at=event.created_at,
        )
        self._event_outbox[outbox_item.id] = outbox_item
        self._save()
        return event.id

    def get_event(self, event_id: UUID) -> Event | None:
        self._maybe_reload()
        for event in self._events:
            if event.id == event_id:
                return event
        return None

    def get_events_by_ids(self, event_ids: list[UUID]) -> dict[UUID, Event]:
        self._maybe_reload()
        wanted = set(event_ids)
        return {event.id: event for event in self._events if event.id in wanted}

    def get_events(self, *, event_type: str | None = None, limit: int = 100) -> list[Event]:
        self._maybe_reload()
        events = list(reversed(self._events))
        if event_type:
            if "%" in event_type or "_" in event_type:
                pattern = event_type.replace("%", "*").replace("_", "?")
                events = [e for e in events if fnmatchcase(e.event_type, pattern)]
            else:
                events = [e for e in events if e.event_type == event_type]
        return events[:limit]

    # ── Event Deliveries / Outbox ───────────────────────────

    def create_event_delivery(self, ed: EventDelivery) -> tuple[UUID, bool]:
        self._maybe_reload()
        for existing in self._event_deliveries.values():
            if existing.event == ed.event and existing.handler == ed.handler:
                return existing.id, False
        ed.created_at = datetime.utcnow()
        self._event_deliveries[ed.id] = ed
        self._save()
        return ed.id, True

    def get_pending_deliveries(self, process_id: UUID) -> list[EventDelivery]:
        self._maybe_reload()
        handler_ids = {h.id for h in self._handlers.values() if h.process == process_id}
        deliveries = [
            delivery for delivery in self._event_deliveries.values()
            if delivery.handler in handler_ids and delivery.status == DeliveryStatus.PENDING
        ]
        deliveries.sort(key=lambda d: d.created_at or datetime.min)
        return deliveries

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        return bool(self.get_pending_deliveries(process_id))

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        delivery = self._event_deliveries.get(delivery_id)
        if delivery is None:
            return False
        delivery.status = DeliveryStatus.DELIVERED
        delivery.run = run_id
        self._save()
        return True

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        delivery = self._event_deliveries.get(delivery_id)
        if delivery is None:
            return False
        delivery.status = DeliveryStatus.QUEUED
        delivery.run = run_id
        self._save()
        return True

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        delivery = self._event_deliveries.get(delivery_id)
        if delivery is None:
            return False
        delivery.status = DeliveryStatus.PENDING
        delivery.run = None
        self._save()
        return True

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        updated = 0
        for delivery in self._event_deliveries.values():
            if delivery.run == run_id and delivery.status == DeliveryStatus.QUEUED:
                delivery.status = DeliveryStatus.DELIVERED
                updated += 1
        if updated:
            self._save()
        return updated

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
        current = self._processes.get(process_id)
        if current and current.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            self.update_process_status(process_id, ProcessStatus.RUNNABLE)

    def claim_event_outbox_batch(
        self,
        *,
        limit: int = 25,
        stale_after_seconds: int = 60,
    ) -> list[EventOutbox]:
        self._maybe_reload()
        now = datetime.utcnow()
        selected: list[EventOutbox] = []
        for item in sorted(self._event_outbox.values(), key=lambda o: (o.created_at or datetime.min, str(o.id))):
            stale = (
                item.status == EventOutboxStatus.PROCESSING
                and item.claimed_at is not None
                and (now - item.claimed_at).total_seconds() > stale_after_seconds
            )
            failed_retry_ready = (
                item.status == EventOutboxStatus.FAILED
                and item.attempt_count < self._event_outbox_failed_max_attempts
                and now - (item.claimed_at or item.created_at or now) >= timedelta(
                    seconds=self._event_outbox_failed_retry_backoff_seconds * (2 ** max(item.attempt_count - 1, 0)),
                )
            )
            if item.status == EventOutboxStatus.PENDING or stale or failed_retry_ready:
                item.status = EventOutboxStatus.PROCESSING
                item.claimed_at = now
                item.attempt_count += 1
                item.last_error = None
                selected.append(item)
            if len(selected) >= limit:
                break
        if selected:
            self._save()
        return selected

    def mark_event_outbox_done(self, outbox_id: UUID) -> bool:
        item = self._event_outbox.get(outbox_id)
        if item is None:
            return False
        item.status = EventOutboxStatus.DONE
        item.completed_at = datetime.utcnow()
        item.last_error = None
        self._save()
        return True

    def mark_event_outbox_failed(self, outbox_id: UUID, error: str) -> bool:
        item = self._event_outbox.get(outbox_id)
        if item is None:
            return False
        item.status = EventOutboxStatus.FAILED
        item.last_error = error[:4000]
        self._save()
        return True

    # ── Runs ─────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        run.created_at = datetime.utcnow()
        self._runs[run.id] = run
        self._save()
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
        result: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.status = status
        run.tokens_in = tokens_in
        run.tokens_out = tokens_out
        run.cost_usd = cost_usd
        run.duration_ms = duration_ms
        run.error = error
        if result is not None:
            run.result = result
        if scope_log is not None:
            run.scope_log = scope_log
        run.completed_at = datetime.utcnow()
        self._save()
        return True

    def get_run(self, run_id: UUID) -> Run | None:
        self._maybe_reload()
        return self._runs.get(run_id)

    def list_runs(self, *, process_id: UUID | None = None, limit: int = 50) -> list[Run]:
        self._maybe_reload()
        runs = list(self._runs.values())
        if process_id:
            runs = [r for r in runs if r.process == process_id]
        runs.sort(key=lambda r: r.created_at or datetime.min, reverse=True)
        return runs[:limit]

    # ── Meta ────────────────────────────────────────────────

    def set_meta(self, key: str, value: str = "") -> None:
        self._meta[key] = {
            "key": key,
            "value": value,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save()

    def get_meta(self, key: str) -> dict[str, str] | None:
        self._maybe_reload()
        return self._meta.get(key)

    # ── Event Types ───────────────────────────────────────────

    def list_event_types(self) -> list[EventType]:
        self._maybe_reload()
        items = list(self._event_types.values())
        items.sort(key=lambda et: et.name)
        return items

    def upsert_event_type(self, et: EventType) -> None:
        if et.name not in self._event_types:
            et.created_at = datetime.utcnow()
        self._event_types[et.name] = et
        self._save()

    def register_event_types(self, names: list[str], source: str = "") -> None:
        changed = False
        for name in names:
            if "*" in name or "?" in name:
                continue
            if name not in self._event_types:
                self._event_types[name] = EventType(
                    name=name, source=source, created_at=datetime.utcnow(),
                )
                changed = True
        if changed:
            self._save()

    def delete_event_type(self, name: str) -> bool:
        if name in self._event_types:
            del self._event_types[name]
            self._save()
            return True
        return False

    # ── Schema CRUD ──────────────────────────────────────────

    def upsert_schema(self, s: Schema) -> UUID:
        for existing in self._schemas.values():
            if existing.name == s.name:
                s.id = existing.id
                s.created_at = existing.created_at
                break
        if s.created_at is None:
            s.created_at = datetime.utcnow()
        self._schemas[s.id] = s
        self._save()
        return s.id

    def get_schema(self, schema_id: UUID) -> Schema | None:
        self._maybe_reload()
        return self._schemas.get(schema_id)

    def get_schema_by_name(self, name: str) -> Schema | None:
        self._maybe_reload()
        for s in self._schemas.values():
            if s.name == name:
                return s
        return None

    def list_schemas(self) -> list[Schema]:
        self._maybe_reload()
        return sorted(self._schemas.values(), key=lambda s: s.name)

    # ── Channel CRUD ─────────────────────────────────────────

    def upsert_channel(self, ch: Channel) -> UUID:
        for existing in self._channels.values():
            if existing.name == ch.name:
                ch.id = existing.id
                ch.created_at = existing.created_at
                break
        if ch.created_at is None:
            ch.created_at = datetime.utcnow()
        self._channels[ch.id] = ch
        self._save()
        return ch.id

    def get_channel(self, channel_id: UUID) -> Channel | None:
        self._maybe_reload()
        return self._channels.get(channel_id)

    def get_channel_by_name(self, name: str) -> Channel | None:
        self._maybe_reload()
        for ch in self._channels.values():
            if ch.name == name:
                return ch
        return None

    def list_channels(self, *, owner_process: UUID | None = None) -> list[Channel]:
        self._maybe_reload()
        channels = list(self._channels.values())
        if owner_process is not None:
            channels = [ch for ch in channels if ch.owner_process == owner_process]
        return sorted(channels, key=lambda ch: ch.name)

    def close_channel(self, channel_id: UUID) -> bool:
        self._maybe_reload()
        ch = self._channels.get(channel_id)
        if ch is None:
            return False
        ch.closed_at = datetime.utcnow()
        self._save()
        return True

    # ── Channel Message CRUD ─────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        if msg.created_at is None:
            msg.created_at = datetime.utcnow()
        self._channel_messages[msg.id] = msg

        # Auto-create deliveries for handlers bound to this channel
        handlers = self.match_handlers_by_channel(msg.channel)
        for handler in handlers:
            delivery = EventDelivery(event=msg.id, handler=handler.id)
            _delivery_id, inserted = self.create_event_delivery(delivery)
            if inserted:
                proc = self.get_process(handler.process)
                if proc and proc.status == ProcessStatus.WAITING:
                    self.update_process_status(handler.process, ProcessStatus.RUNNABLE)

        self._save()
        return msg.id

    def list_channel_messages(self, channel_id: UUID, *, limit: int = 100) -> list[ChannelMessage]:
        self._maybe_reload()
        msgs = [m for m in self._channel_messages.values() if m.channel == channel_id]
        msgs.sort(key=lambda m: m.created_at or datetime.min)
        return msgs[:limit]

    # ── Handler by Channel ───────────────────────────────────

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        self._maybe_reload()
        return [h for h in self._handlers.values() if h.channel == channel_id and h.enabled]

"""In-memory CogOS repository with JSON file persistence for local development."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from cogos.db.models import (
    Capability,
    Cron,
    Event,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessStatus,
    Resource,
    ResourceType,
    Run,
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

        self._processes: dict[UUID, Process] = {}
        self._capabilities: dict[UUID, Capability] = {}
        self._handlers: dict[UUID, Handler] = {}
        self._files: dict[UUID, File] = {}
        self._file_versions: dict[UUID, list[FileVersion]] = {}  # keyed by file_id
        self._process_capabilities: dict[UUID, ProcessCapability] = {}
        self._resources: dict[str, Resource] = {}  # keyed by name
        self._cron_rules: dict[UUID, Cron] = {}
        self._events: list[Event] = []
        self._runs: dict[UUID, Run] = {}

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
        self._runs.clear()

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
        for r in data.get("runs", []):
            run = Run(**r)
            self._runs[run.id] = run

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
            "runs": [r.model_dump(mode="json") for r in self._runs.values()],
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
        self._runs.clear()
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

    def list_processes(self, *, status: ProcessStatus | None = None, limit: int = 200) -> list[Process]:
        self._maybe_reload()
        procs = list(self._processes.values())
        if status:
            procs = [p for p in procs if p.status == status]
        procs.sort(key=lambda p: p.name)
        return procs[:limit]

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
        # Upsert by (process, event_pattern) to match RDS ON CONFLICT behavior
        for existing in self._handlers.values():
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
        handlers.sort(key=lambda h: h.event_pattern)
        return handlers

    def delete_handler(self, handler_id: UUID) -> bool:
        if handler_id in self._handlers:
            del self._handlers[handler_id]
            self._save()
            return True
        return False

    # ── Process Capabilities ────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        """Upsert a process-capability binding by (process, capability) pair."""
        for existing in self._process_capabilities.values():
            if existing.process == pc.process and existing.capability == pc.capability:
                return existing.id
        self._process_capabilities[pc.id] = pc
        self._save()
        return pc.id

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
                        "delegatable": pc.delegatable,
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

    def list_cron_rules(self) -> list[Cron]:
        self._maybe_reload()
        rules = list(self._cron_rules.values())
        rules.sort(key=lambda c: c.expression)
        return rules

    # ── Events ───────────────────────────────────────────────

    def append_event(self, event: Event) -> UUID:
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

    # ── Runs ─────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        run.created_at = datetime.utcnow()
        self._runs[run.id] = run
        self._save()
        return run.id

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

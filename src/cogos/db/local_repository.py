"""In-memory CogOS repository with JSON file persistence for local development."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from cogos.db.models import (
    ALL_EPOCHS,
    Capability,
    Channel,
    ChannelMessage,
    CogosOperation,
    Cron,
    Delivery,
    DeliveryStatus,
    File,
    FileVersion,
    Handler,
    Process,
    ProcessCapability,
    ProcessStatus,
    Resource,
    Run,
    RunStatus,
    Schema,
)
from cogos.db.models.discord_metadata import DiscordChannel, DiscordGuild

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
        self._lock_file = self._data_dir / "cogos_data.lock"
        self._file_mtime: float = 0.0
        self._write_depth = 0
        self._processes: dict[UUID, Process] = {}
        self._capabilities: dict[UUID, Capability] = {}
        self._handlers: dict[UUID, Handler] = {}
        self._files: dict[UUID, File] = {}
        self._file_versions: dict[UUID, list[FileVersion]] = {}  # keyed by file_id
        self._process_capabilities: dict[UUID, ProcessCapability] = {}
        self._resources: dict[str, Resource] = {}  # keyed by name
        self._cron_rules: dict[UUID, Cron] = {}
        self._deliveries: dict[UUID, Delivery] = {}
        self._runs: dict[UUID, Run] = {}
        self._schemas: dict[UUID, Schema] = {}
        self._channels: dict[UUID, Channel] = {}
        self._channel_messages: dict[UUID, ChannelMessage] = {}
        self._discord_guilds: dict[str, DiscordGuild] = {}
        self._discord_channels: dict[str, DiscordChannel] = {}
        self._meta: dict[str, dict[str, str]] = {}
        self._alerts: dict[UUID, Any] = {}
        self._operations: dict[UUID, CogosOperation] = {}
        self._reboot_epoch: int = 0

        self._load()

    # ── Persistence ──────────────────────────────────────────

    def _reset_state(self) -> None:
        self._processes.clear()
        self._capabilities.clear()
        self._handlers.clear()
        self._process_capabilities.clear()
        self._resources.clear()
        self._cron_rules.clear()
        self._files.clear()
        self._file_versions.clear()
        self._deliveries.clear()
        self._runs.clear()
        self._schemas.clear()
        self._channels.clear()
        self._channel_messages.clear()
        self._discord_guilds.clear()
        self._discord_channels.clear()
        self._meta.clear()
        self._operations.clear()
        self._reboot_epoch = 0

    def _read_persisted_data(self) -> dict[str, Any]:
        if not self._file.exists():
            return {}
        try:
            return json.loads(self._file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not load cogos data from %s", self._file)
            return {}

    def _serialize_state(self) -> dict[str, Any]:
        return {
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
            "deliveries": [ed.model_dump(mode="json") for ed in self._deliveries.values()],
            "runs": [r.model_dump(mode="json") for r in self._runs.values()],
            "schemas": [s.model_dump(mode="json") for s in self._schemas.values()],
            "channels": [ch.model_dump(mode="json") for ch in self._channels.values()],
            "channel_messages": [m.model_dump(mode="json") for m in self._channel_messages.values()],
            "discord_guilds": [g.model_dump(mode="json") for g in self._discord_guilds.values()],
            "discord_channels": [ch.model_dump(mode="json") for ch in self._discord_channels.values()],
            "operations": [op.model_dump(mode="json") for op in self._operations.values()],
            "reboot_epoch": self._reboot_epoch,
            "meta": self._meta,
        }

    @staticmethod
    def _row_key(row: dict[str, Any], *fields: str) -> Any:
        if len(fields) == 1:
            return row.get(fields[0])
        return tuple(row.get(field) for field in fields)

    @classmethod
    def _merge_rows(
        cls,
        latest_rows: list[dict[str, Any]],
        current_rows: list[dict[str, Any]],
        *,
        primary_fields: tuple[str, ...],
        conflict_fields: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        merged = {
            cls._row_key(row, *primary_fields): row
            for row in latest_rows
        }
        conflicts = {}
        if conflict_fields:
            conflicts = {
                cls._row_key(row, *conflict_fields): cls._row_key(row, *primary_fields)
                for row in latest_rows
            }

        for row in current_rows:
            primary_key = cls._row_key(row, *primary_fields)
            if conflict_fields:
                conflict_key = cls._row_key(row, *conflict_fields)
                previous_primary = conflicts.get(conflict_key)
                if previous_primary is not None and previous_primary != primary_key:
                    merged.pop(previous_primary, None)
                conflicts[conflict_key] = primary_key
            merged[primary_key] = row

        return list(merged.values())

    @classmethod
    def _merge_serialized_data(
        cls,
        latest_data: dict[str, Any],
        current_data: dict[str, Any],
    ) -> dict[str, Any]:
        specs: dict[str, tuple[tuple[str, ...], tuple[str, ...] | None]] = {
            "processes": (("id",), ("name",)),
            "capabilities": (("id",), ("name",)),
            "handlers": (("id",), ("process", "channel")),
            "process_capabilities": (("id",), ("process", "name")),
            "files": (("id",), ("key",)),
            "file_versions": (("id",), ("file_id", "version")),
            "resources": (("id",), ("name",)),
            "cron_rules": (("id",), ("expression", "channel_name")),
            "deliveries": (("id",), ("message", "handler")),
            "runs": (("id",), None),
            "schemas": (("id",), ("name",)),
            "channels": (("id",), ("name",)),
            "channel_messages": (("id",), None),
            "discord_guilds": (("guild_id",), None),
            "discord_channels": (("channel_id",), None),
            "operations": (("id",), None),
        }

        merged = {}
        for key, (primary_fields, conflict_fields) in specs.items():
            merged[key] = cls._merge_rows(
                latest_data.get(key, []),
                current_data.get(key, []),
                primary_fields=primary_fields,
                conflict_fields=conflict_fields,
            )

        merged["meta"] = dict(latest_data.get("meta", {}))
        merged["meta"].update(current_data.get("meta", {}))
        merged["reboot_epoch"] = max(
            latest_data.get("reboot_epoch", 0),
            current_data.get("reboot_epoch", 0),
        )
        return merged

    def _populate_from_data(self, data: dict[str, Any]) -> None:
        self._reset_state()

        for f in data.get("files", []):
            file = File(**f)
            self._files[file.id] = file
        for fv in data.get("file_versions", []):
            version = FileVersion(**fv)
            self._file_versions.setdefault(version.file_id, []).append(version)
        for p in data.get("processes", []):
            proc = Process(**self._migrate_legacy_process_prompt(p))
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
            resource = Resource(**res)
            self._resources[resource.name] = resource
        for cr in data.get("cron_rules", []):
            cron = Cron(**cr)
            self._cron_rules[cron.id] = cron
        for ed in data.get("deliveries", data.get("event_deliveries", [])):
            delivery = Delivery(**ed)
            self._deliveries[delivery.id] = delivery
        for r in data.get("runs", []):
            run = Run(**r)
            self._runs[run.id] = run
        for s in data.get("schemas", []):
            schema = Schema(**s)
            self._schemas[schema.id] = schema
        for ch in data.get("channels", []):
            channel = Channel(**ch)
            self._channels[channel.id] = channel
        for cm in data.get("channel_messages", []):
            message = ChannelMessage(**cm)
            self._channel_messages[message.id] = message
        for g in data.get("discord_guilds", []):
            guild = DiscordGuild(**g)
            self._discord_guilds[guild.guild_id] = guild
        for dch in data.get("discord_channels", []):
            dchannel = DiscordChannel(**dch)
            self._discord_channels[dchannel.channel_id] = dchannel
        self._meta.update(data.get("meta", {}))
        self._reboot_epoch = data.get("reboot_epoch", 0)
        for op in data.get("operations", []):
            operation = CogosOperation(**op)
            self._operations[operation.id] = operation

    def _migrate_legacy_process_prompt(self, raw: dict[str, Any]) -> dict[str, Any]:
        migrated = dict(raw)
        refs: list[str] = []

        raw_files = raw.get("files") or []
        if not raw_files and raw.get("code"):
            raw_files = [raw["code"]]

        for file_id in raw_files:
            try:
                fid = UUID(str(file_id))
            except (TypeError, ValueError):
                continue
            file = self._files.get(fid)
            if file is None:
                continue
            refs.append(f"@{{{file.key}}}")

        if not refs:
            return migrated

        content = raw.get("content", "") or ""
        missing_refs = [ref for ref in refs if ref not in content]
        if not missing_refs:
            return migrated

        migrated["content"] = "\n\n".join([*missing_refs, content] if content else missing_refs)
        return migrated

    @contextmanager
    def _writing(self, *, force: bool = False):
        outermost = self._write_depth == 0
        if outermost:
            self._maybe_reload()
        self._write_depth += 1
        committed = False
        try:
            yield
            committed = True
        finally:
            self._write_depth -= 1
            if outermost and committed:
                if force:
                    self._force_save()
                else:
                    self._save()

    def _maybe_reload(self) -> None:
        if self._write_depth > 0:
            return
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
        self._file_mtime = self._file.stat().st_mtime
        data = self._read_persisted_data()
        self._populate_from_data(data)

        logger.info(
            "Loaded cogos data: %d processes, %d capabilities, %d files, %d deliveries, %d runs",
            len(self._processes), len(self._capabilities), len(self._files),
            len(self._deliveries), len(self._runs),
        )

    def _save(self) -> None:
        current_data = self._serialize_state()
        self._lock_file.touch(exist_ok=True)
        with self._lock_file.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                latest_data = self._read_persisted_data()
                merged = self._merge_serialized_data(latest_data, current_data)
                tmp_file = self._data_dir / f".{self._file.name}.{os.getpid()}.tmp"
                tmp_file.write_text(json.dumps(merged, indent=2, default=_json_serial))
                tmp_file.replace(self._file)
                self._file_mtime = self._file.stat().st_mtime
                self._populate_from_data(merged)
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _force_save(self) -> None:
        """Save in-memory state directly, overwriting disk without merging."""
        current_data = self._serialize_state()
        self._lock_file.touch(exist_ok=True)
        with self._lock_file.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                tmp_file = self._data_dir / f".{self._file.name}.{os.getpid()}.tmp"
                tmp_file.write_text(json.dumps(current_data, indent=2, default=_json_serial))
                tmp_file.replace(self._file)
                self._file_mtime = self._file.stat().st_mtime
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    # ── Epoch & Operations ────────────────────────────────────

    @property
    def reboot_epoch(self) -> int:
        self._maybe_reload()
        return self._reboot_epoch

    def increment_epoch(self) -> int:
        with self._writing():
            self._reboot_epoch += 1
            return self._reboot_epoch

    def add_operation(self, op: CogosOperation) -> UUID:
        with self._writing():
            op.created_at = op.created_at or datetime.now(UTC)
            self._operations[op.id] = op
            return op.id

    def list_operations(self, limit: int = 50) -> list[CogosOperation]:
        self._maybe_reload()
        ops = list(self._operations.values())
        ops.sort(key=lambda o: o.created_at or datetime.min, reverse=True)
        return ops[:limit]

    # ── Raw query stubs (used by cogos_events router) ────────

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return 0

    def clear_all(self) -> None:
        """Wipe all in-memory data and persist the empty state."""
        with self._writing(force=True):
            self._reset_state()

    def clear_config(self) -> None:
        """Clear config, process, and message data, preserving files, channels, and Discord metadata."""
        with self._writing(force=True):
            self._runs.clear()
            self._deliveries.clear()
            self._channel_messages.clear()
            self._handlers.clear()
            self._processes.clear()
            self._capabilities.clear()
            self._process_capabilities.clear()
            self._resources.clear()
            self._cron_rules.clear()
            self._schemas.clear()

    def delete_files_by_prefixes(self, prefixes: list[str]) -> int:
        """Delete all files whose key starts with any of the given prefixes. Returns count deleted."""
        count = 0
        with self._writing(force=True):
            to_delete = [
                fid for fid, f in self._files.items()
                if any(f.key.startswith(p) for p in prefixes)
            ]
            for fid in to_delete:
                del self._files[fid]
                self._file_versions.pop(fid, None)
                count += 1
        return count

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
        with self._writing():
            now = datetime.now(UTC)
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
                p.epoch = p.epoch or self._reboot_epoch
            p.updated_at = now
            self._processes[p.id] = p
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
        with self._writing():
            if process_id in self._processes:
                del self._processes[process_id]
                return True
            return False

    def list_processes(self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None) -> list[Process]:
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        procs = list(self._processes.values())
        if effective_epoch != ALL_EPOCHS:
            procs = [p for p in procs if p.epoch == effective_epoch]
        if status:
            procs = [p for p in procs if p.status == status]
        procs.sort(key=lambda p: p.name)
        return procs[:limit]

    def update_process_status(self, process_id: UUID, status: ProcessStatus) -> bool:
        with self._writing():
            process = self._processes.get(process_id)
            if process is None:
                return False
            process.status = status
            if status == ProcessStatus.RUNNABLE:
                process.runnable_since = process.runnable_since or datetime.now(UTC)
            else:
                process.runnable_since = None
            process.updated_at = datetime.now(UTC)
            # Cascade: if disabling, recursively disable all children
            if status == ProcessStatus.DISABLED:
                self._cascade_disable(process_id)
            return True

    def _cascade_disable(self, parent_id: UUID) -> None:
        """Recursively disable all child processes.

        Must be called inside a _writing() block.
        """
        children = [p for p in self._processes.values() if p.parent_process == parent_id]
        for child in children:
            if child.status not in (ProcessStatus.DISABLED, ProcessStatus.COMPLETED):
                child.status = ProcessStatus.DISABLED
                child.runnable_since = None
                child.updated_at = datetime.now(UTC)
                self._cascade_disable(child.id)

    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        self._maybe_reload()
        runnable = [p for p in self._processes.values()
                    if p.status == ProcessStatus.RUNNABLE and p.epoch == self._reboot_epoch]
        runnable.sort(key=lambda p: (-p.priority, p.runnable_since or datetime.max, p.name))
        return runnable[:limit]

    def increment_retry(self, process_id: UUID) -> bool:
        with self._writing():
            process = self._processes.get(process_id)
            if process is None:
                return False
            process.retry_count += 1
            process.updated_at = datetime.now(UTC)
            return True

    # ── Capabilities ─────────────────────────────────────────

    def upsert_capability(self, cap: Capability) -> UUID:
        with self._writing():
            now = datetime.now(UTC)
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

    def search_capabilities(self, query: str, *, process_id: UUID | None = None) -> list[Capability]:
        """Search capabilities by name/description matching. Optionally scoped to a process."""
        self._maybe_reload()
        q = query.lower()
        if process_id:
            bound_cap_ids = {pc.capability for pc in self._process_capabilities.values() if pc.process == process_id}
            caps = [c for c in self._capabilities.values()
                    if c.enabled and c.id in bound_cap_ids
                    and (q in c.name.lower() or q in (c.description or "").lower())]
        else:
            caps = [c for c in self._capabilities.values()
                    if c.enabled and (q in c.name.lower() or q in (c.description or "").lower())]
        caps.sort(key=lambda c: c.name)
        return caps

    # ── Handlers ─────────────────────────────────────────────

    def create_handler(self, h: Handler) -> UUID:
        with self._writing():
            # Upsert by (process, channel)
            for existing in self._handlers.values():
                if h.channel is not None:
                    if existing.process == h.process and existing.channel == h.channel:
                        existing.enabled = h.enabled
                        return existing.id
            h.epoch = self._reboot_epoch
            h.created_at = datetime.now(UTC)
            self._handlers[h.id] = h
            return h.id

    def list_handlers(self, *, process_id: UUID | None = None, enabled_only: bool = False, epoch: int | None = None) -> list[Handler]:
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        handlers = list(self._handlers.values())
        if effective_epoch != ALL_EPOCHS:
            handlers = [h for h in handlers if h.epoch == effective_epoch]
        if process_id:
            handlers = [h for h in handlers if h.process == process_id]
        if enabled_only:
            handlers = [h for h in handlers if h.enabled]
        handlers.sort(key=lambda h: str(h.channel or ""))
        return handlers

    def delete_handler(self, handler_id: UUID) -> bool:
        with self._writing():
            if handler_id in self._handlers:
                del self._handlers[handler_id]
                return True
            return False

    def match_handlers(self, event_type: str) -> list[Handler]:
        """Legacy event-era compatibility stub.

        The active runtime binds handlers to channels, not event patterns, so
        old event-pattern matching no longer exists. Keep this method as a
        no-op for older callers that still import it.
        """
        # Legacy API: channel-based code should call match_handlers_by_channel().
        return []

    # ── Process Capabilities ────────────────────────────────

    def create_process_capability(self, pc: ProcessCapability) -> UUID:
        """Upsert a process-capability binding by (process, name) pair."""
        with self._writing():
            for existing in self._process_capabilities.values():
                if existing.process == pc.process and existing.name == pc.name:
                    existing.capability = pc.capability
                    existing.config = pc.config
                    return existing.id
            pc.epoch = self._reboot_epoch
            self._process_capabilities[pc.id] = pc
            return pc.id

    def delete_process_capability(self, pc_id: UUID) -> bool:
        with self._writing():
            if pc_id in self._process_capabilities:
                del self._process_capabilities[pc_id]
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
        with self._writing():
            now = datetime.now(UTC)
            f.created_at = now
            f.updated_at = now
            self._files[f.id] = f
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

    def grep_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 100
    ) -> list[tuple[str, str]]:
        """Search active file versions by regex pattern. Returns (key, content) tuples."""
        import re

        self._maybe_reload()
        results: list[tuple[str, str]] = []
        for f in sorted(self._files.values(), key=lambda f: f.key):
            if prefix and not f.key.startswith(prefix):
                continue
            fv = self.get_active_file_version(f.id)
            if fv and re.search(pattern, fv.content):
                results.append((f.key, fv.content))
                if len(results) >= limit:
                    break
        return results

    def glob_files(
        self, pattern: str, *, prefix: str | None = None, limit: int = 200
    ) -> list[str]:
        """Match file keys by glob pattern. Returns list of matching keys."""
        from cogos.db.repository import Repository

        import re

        regex = Repository._glob_to_regex(pattern)
        self._maybe_reload()
        results: list[str] = []
        for f in sorted(self._files.values(), key=lambda f: f.key):
            if prefix and not f.key.startswith(prefix):
                continue
            if re.match(regex, f.key):
                results.append(f.key)
                if len(results) >= limit:
                    break
        return results

    def update_file_includes(self, file_id: UUID, includes: list[str]) -> bool:
        with self._writing():
            file = self._files.get(file_id)
            if not file:
                return False
            file.includes = includes
            file.updated_at = datetime.now(UTC)
            return True

    def delete_file(self, file_id: UUID) -> bool:
        with self._writing(force=True):
            if file_id in self._files:
                del self._files[file_id]
                self._file_versions.pop(file_id, None)
                return True
            return False

    def insert_file_version(self, fv: FileVersion) -> None:
        with self._writing():
            fv.created_at = datetime.now(UTC)
            self._file_versions.setdefault(fv.file_id, []).append(fv)
            if fv.file_id in self._files:
                self._files[fv.file_id].updated_at = datetime.now(UTC)

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
        with self._writing():
            for fv in self._file_versions.get(file_id, []):
                fv.is_active = fv.version == version

    def delete_file_version(self, file_id: UUID, version: int) -> bool:
        with self._writing(force=True):
            versions = self._file_versions.get(file_id, [])
            before = len(versions)
            self._file_versions[file_id] = [v for v in versions if v.version != version]
            if len(self._file_versions[file_id]) < before:
                return True
            return False

    def update_file_version_content(self, file_id: UUID, version: int, content: str) -> bool:
        with self._writing():
            for fv in self._file_versions.get(file_id, []):
                if fv.version == version:
                    fv.content = content
                    return True
            return False

    # ── Resources ─────────────────────────────────────────────

    def upsert_resource(self, r: Resource) -> str:
        with self._writing():
            now = datetime.now(UTC)
            existing = self._resources.get(r.name)
            if existing:
                r.id = existing.id
                r.created_at = existing.created_at
            else:
                r.created_at = now
            self._resources[r.name] = r
            return r.name

    def list_resources(self) -> list[Resource]:
        self._maybe_reload()
        resources = list(self._resources.values())
        resources.sort(key=lambda r: r.name)
        return resources

    # ── Cron Rules ────────────────────────────────────────────

    def upsert_cron(self, c: Cron) -> UUID:
        with self._writing():
            now = datetime.now(UTC)
            # Match by (expression, channel_name)
            existing = None
            for ec in self._cron_rules.values():
                if ec.expression == c.expression and ec.channel_name == c.channel_name:
                    existing = ec
                    break
            if existing:
                c.id = existing.id
                c.created_at = existing.created_at
            else:
                c.created_at = now
            self._cron_rules[c.id] = c
            return c.id

    def list_cron_rules(self, *, enabled_only: bool = False) -> list[Cron]:
        self._maybe_reload()
        rules = list(self._cron_rules.values())
        if enabled_only:
            rules = [c for c in rules if c.enabled]
        rules.sort(key=lambda c: c.expression)
        return rules

    # ── Deliveries ───────────────────────────────────────────

    def create_delivery(self, ed: Delivery) -> tuple[UUID, bool]:
        with self._writing():
            for existing in self._deliveries.values():
                if existing.message == ed.message and existing.handler == ed.handler:
                    return existing.id, False
            ed.epoch = self._reboot_epoch
            ed.created_at = datetime.now(UTC)
            self._deliveries[ed.id] = ed
            return ed.id, True

    def get_pending_deliveries(self, process_id: UUID) -> list[Delivery]:
        self._maybe_reload()
        handler_ids = {h.id for h in self._handlers.values() if h.process == process_id}
        deliveries = [
            delivery for delivery in self._deliveries.values()
            if delivery.handler in handler_ids and delivery.status == DeliveryStatus.PENDING
        ]
        deliveries.sort(key=lambda d: d.created_at or datetime.min)
        return deliveries

    def list_deliveries(
        self,
        *,
        message_id: UUID | None = None,
        handler_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 500,
        epoch: int | None = None,
    ) -> list[Delivery]:
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        deliveries = list(self._deliveries.values())
        if effective_epoch != ALL_EPOCHS:
            deliveries = [d for d in deliveries if d.epoch == effective_epoch]
        if message_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.message == message_id]
        if handler_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.handler == handler_id]
        if run_id is not None:
            deliveries = [delivery for delivery in deliveries if delivery.run == run_id]
        deliveries.sort(key=lambda d: d.created_at or datetime.min, reverse=True)
        return deliveries[:limit]

    def has_pending_deliveries(self, process_id: UUID) -> bool:
        return bool(self.get_pending_deliveries(process_id))

    def get_latest_delivery_time(self, handler_id: UUID):
        self._maybe_reload()
        times = [
            self._channel_messages[d.message].created_at
            for d in self._deliveries.values()
            if d.handler == handler_id and d.message in self._channel_messages
            and self._channel_messages[d.message].created_at
        ]
        return max(times) if times else None

    def mark_delivered(self, delivery_id: UUID, run_id: UUID) -> bool:
        with self._writing():
            delivery = self._deliveries.get(delivery_id)
            if delivery is None:
                return False
            delivery.status = DeliveryStatus.DELIVERED
            delivery.run = run_id
            return True

    def mark_queued(self, delivery_id: UUID, run_id: UUID) -> bool:
        with self._writing():
            delivery = self._deliveries.get(delivery_id)
            if delivery is None:
                return False
            delivery.status = DeliveryStatus.QUEUED
            delivery.run = run_id
            return True

    def requeue_delivery(self, delivery_id: UUID) -> bool:
        with self._writing():
            delivery = self._deliveries.get(delivery_id)
            if delivery is None:
                return False
            delivery.status = DeliveryStatus.PENDING
            delivery.run = None
            return True

    def mark_run_deliveries_delivered(self, run_id: UUID) -> int:
        with self._writing():
            updated = 0
            for delivery in self._deliveries.values():
                if delivery.run == run_id and delivery.status == DeliveryStatus.QUEUED:
                    delivery.status = DeliveryStatus.DELIVERED
                    updated += 1
            return updated

    def rollback_dispatch(
        self,
        process_id: UUID,
        run_id: UUID,
        delivery_id: UUID | None = None,
        *,
        error: str | None = None,
    ) -> None:
        with self._writing():
            if delivery_id is not None:
                self.requeue_delivery(delivery_id)
            self.complete_run(run_id, status=RunStatus.FAILED, error=(error or "executor invoke failed")[:4000])
            current = self._processes.get(process_id)
            if current and current.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
                self.update_process_status(process_id, ProcessStatus.RUNNABLE)

    # ── Runs ─────────────────────────────────────────────────

    def create_run(self, run: Run) -> UUID:
        with self._writing():
            run.epoch = self._reboot_epoch
            run.created_at = datetime.now(UTC)
            self._runs[run.id] = run
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
        model_version: str | None = None,
        result: dict | None = None,
        snapshot: dict | None = None,
        scope_log: list[dict] | None = None,
    ) -> bool:
        with self._writing():
            run = self._runs.get(run_id)
            if run is None:
                return False
            run.status = status
            run.tokens_in = tokens_in
            run.tokens_out = tokens_out
            run.cost_usd = cost_usd
            run.duration_ms = duration_ms
            run.error = error
            if model_version is not None:
                run.model_version = model_version
            if result is not None:
                run.result = result
            if snapshot is not None:
                run.snapshot = snapshot
            if scope_log is not None:
                run.scope_log = scope_log
            run.completed_at = datetime.now(UTC)
            return True

    def timeout_stale_runs(self, max_age_ms: int = 900_000) -> int:
        """Mark RUNNING runs older than max_age_ms as TIMEOUT."""
        now = datetime.now(UTC)
        count = 0
        with self._writing():
            for run in self._runs.values():
                if run.status != RunStatus.RUNNING:
                    continue
                if run.created_at is None:
                    continue
                age_ms = (now - run.created_at).total_seconds() * 1000
                if age_ms > max_age_ms:
                    run.status = RunStatus.TIMEOUT
                    run.error = "Run exceeded maximum duration and was reaped by dispatcher"
                    run.completed_at = now
                    count += 1
        return count

    def get_run(self, run_id: UUID) -> Run | None:
        self._maybe_reload()
        return self._runs.get(run_id)

    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        """List runs that failed or timed out within the last max_age_ms."""
        self._maybe_reload()
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(milliseconds=max_age_ms)
        result = []
        for run in self._runs.values():
            if run.epoch != self._reboot_epoch:
                continue
            if run.status in (RunStatus.FAILED, RunStatus.TIMEOUT, RunStatus.THROTTLED):
                if run.completed_at and run.completed_at >= cutoff:
                    result.append(run)
                elif run.created_at and run.created_at >= cutoff:
                    result.append(run)
        return result

    def update_run_metadata(self, run_id: UUID, metadata: dict) -> None:
        with self._writing():
            run = self._runs.get(run_id)
            if run:
                run.metadata = metadata

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
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        runs = list(self._runs.values())
        if effective_epoch != ALL_EPOCHS:
            runs = [r for r in runs if r.epoch == effective_epoch]
        if process_id:
            runs = [r for r in runs if r.process == process_id]
        if process_ids:
            pid_set = set(process_ids)
            runs = [r for r in runs if r.process in pid_set]
        if status:
            runs = [r for r in runs if (r.status.value if hasattr(r.status, "value") else r.status) == status]
        if since:
            from datetime import datetime as dt
            cutoff = dt.fromisoformat(since.replace("Z", "+00:00"))
            runs = [r for r in runs if r.created_at and r.created_at >= cutoff]
        runs.sort(key=lambda r: r.created_at or datetime.min, reverse=True)
        return runs[:limit]

    def list_file_mutations(self, run_id: UUID) -> list[dict]:
        """List file versions created by a specific run."""
        self._maybe_reload()
        results = []
        for file_id, versions in self._file_versions.items():
            for fv in versions:
                if fv.run_id == run_id:
                    f = self._files.get(file_id)
                    if f:
                        results.append({
                            "key": f.key,
                            "version": fv.version,
                            "created_at": fv.created_at,
                        })
        results.sort(key=lambda r: r.get("created_at") or datetime.min)
        return results

    def list_runs_by_process_glob(
        self,
        name_pattern: str,
        *,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[Run]:
        """List runs for processes whose name matches a glob pattern."""
        import fnmatch
        self._maybe_reload()
        # Build name->id map
        matching_pids = set()
        for proc in self._processes.values():
            if fnmatch.fnmatch(proc.name, name_pattern):
                matching_pids.add(proc.id)
        return self.list_runs(process_ids=list(matching_pids), status=status, since=since, limit=limit)

    # ── Meta ────────────────────────────────────────────────

    def set_meta(self, key: str, value: str = "") -> None:
        with self._writing():
            self._meta[key] = {
                "key": key,
                "value": value,
                "updated_at": datetime.now(UTC).isoformat(),
            }

    def get_meta(self, key: str) -> dict[str, str] | None:
        self._maybe_reload()
        return self._meta.get(key)

    # ── Schema CRUD ──────────────────────────────────────────

    def upsert_schema(self, s: Schema) -> UUID:
        with self._writing():
            for existing in self._schemas.values():
                if existing.name == s.name:
                    s.id = existing.id
                    s.created_at = existing.created_at
                    break
            if s.created_at is None:
                s.created_at = datetime.now(UTC)
            self._schemas[s.id] = s
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
        with self._writing():
            for existing in self._channels.values():
                if existing.name == ch.name:
                    ch.id = existing.id
                    ch.created_at = existing.created_at
                    break
            if ch.created_at is None:
                ch.created_at = datetime.now(UTC)
            self._channels[ch.id] = ch
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
        with self._writing():
            ch = self._channels.get(channel_id)
            if ch is None:
                return False
            ch.closed_at = datetime.now(UTC)
            return True

    # ── Channel Message CRUD ─────────────────────────────────

    def append_channel_message(self, msg: ChannelMessage) -> UUID:
        with self._writing():
            if msg.created_at is None:
                msg.created_at = datetime.now(UTC)

            # Idempotency check
            if msg.idempotency_key:
                for existing in self._channel_messages.values():
                    if (existing.channel == msg.channel
                            and existing.idempotency_key == msg.idempotency_key):
                        return existing.id

            self._channel_messages[msg.id] = msg

            # Auto-create deliveries for handlers bound to this channel
            handlers = self.match_handlers_by_channel(msg.channel)
            for handler in handlers:
                delivery = Delivery(message=msg.id, handler=handler.id, trace_id=msg.trace_id)
                _delivery_id, inserted = self.create_delivery(delivery)
                if inserted:
                    proc = self.get_process(handler.process)
                    if proc and proc.status == ProcessStatus.WAITING:
                        self.update_process_status(handler.process, ProcessStatus.RUNNABLE)

            return msg.id

    def list_channel_messages(self, channel_id: UUID | None = None, *, limit: int = 100, since=None) -> list[ChannelMessage]:
        self._maybe_reload()
        msgs = list(self._channel_messages.values())
        if channel_id is not None:
            msgs = [m for m in msgs if m.channel == channel_id]
        if since:
            msgs = [m for m in msgs if m.created_at and m.created_at > since]
        if channel_id is not None:
            msgs.sort(key=lambda m: m.created_at or datetime.min)
        else:
            msgs.sort(key=lambda m: m.created_at or datetime.min, reverse=True)
        return msgs[:limit]

    # ── Handler by Channel ───────────────────────────────────

    def match_handlers_by_channel(self, channel_id: UUID) -> list[Handler]:
        self._maybe_reload()
        return [h for h in self._handlers.values() if h.channel == channel_id and h.enabled]

    # ── Discord Metadata ────────────────────────────────────

    def upsert_discord_guild(self, guild: DiscordGuild) -> None:
        from datetime import timezone
        guild.synced_at = datetime.now(timezone.utc)
        self._discord_guilds[guild.guild_id] = guild
        self._save()

    def get_discord_guild(self, guild_id: str) -> DiscordGuild | None:
        self._maybe_reload()
        return self._discord_guilds.get(guild_id)

    def list_discord_guilds(self, cogent_name: str | None = None) -> list[DiscordGuild]:
        self._maybe_reload()
        guilds = list(self._discord_guilds.values())
        if cogent_name:
            guilds = [g for g in guilds if g.cogent_name == cogent_name]
        return guilds

    def delete_discord_guild(self, guild_id: str) -> None:
        with self._writing(force=True):
            self._discord_guilds.pop(guild_id, None)
            self._discord_channels = {k: v for k, v in self._discord_channels.items() if v.guild_id != guild_id}

    def upsert_discord_channel(self, channel: DiscordChannel) -> None:
        from datetime import timezone
        channel.synced_at = datetime.now(timezone.utc)
        self._discord_channels[channel.channel_id] = channel
        self._save()

    def get_discord_channel(self, channel_id: str) -> DiscordChannel | None:
        self._maybe_reload()
        return self._discord_channels.get(channel_id)

    def list_discord_channels(self, guild_id: str | None = None) -> list[DiscordChannel]:
        self._maybe_reload()
        channels = list(self._discord_channels.values())
        if guild_id:
            channels = [ch for ch in channels if ch.guild_id == guild_id]
        return sorted(channels, key=lambda ch: ch.position)

    def delete_discord_channel(self, channel_id: str) -> None:
        with self._writing(force=True):
            self._discord_channels.pop(channel_id, None)

    # ── Alerts ────────────────────────────────────────────────

    def create_alert(
        self,
        severity: str,
        alert_type: str,
        source: str,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        from cogos.db.models.alert import Alert, AlertSeverity

        alert = Alert(
            severity=AlertSeverity(severity),
            alert_type=alert_type,
            source=source,
            message=message,
            metadata=metadata or {},
        )
        with self._writing():
            self._alerts[alert.id] = alert

    def list_alerts(self, *, resolved: bool = False, limit: int = 50) -> list:
        self._maybe_reload()
        from cogos.db.models.alert import Alert

        alerts = list(self._alerts.values())
        if not resolved:
            alerts = [a for a in alerts if a.resolved_at is None]
        return sorted(alerts, key=lambda a: a.created_at or datetime.min, reverse=True)[:limit]

"""Process capabilities — list, get, and spawn processes."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.process_handle import ProcessHandle
from cogos.db.models import Channel, ChannelType, Handler, Process, ProcessCapability, ProcessMode, ProcessStatus
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class ProcessSummary(BaseModel):
    id: str
    name: str
    mode: str
    status: str
    priority: float
    required_tags: list[str] = []
    parent_process: str | None = None


class ProcessDetail(ProcessSummary):
    content: str = ""
    code: str | None = None
    preemptible: bool = False
    model: str | None = None
    max_retries: int = 0
    retry_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class SpawnResult(BaseModel):
    id: str
    name: str
    status: str
    parent_process: str


class ProcessError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────


class ProcsCapability(Capability):
    """Process management.

    Usage:
        procs.list()
        procs.get(name="worker")
        procs.spawn(name="subtask", content="do something")
    """

    ALL_OPS = {"list", "get", "spawn", "detach"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        return {"ops": sorted(old_ops & new_ops)}

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed by scope (allowed: {sorted(allowed)})")

    def list(self, status: str | None = None, limit: int = 200) -> list[ProcessSummary]:
        """List processes, optionally filtered by status."""
        self._check("list")
        ps = ProcessStatus(status) if status else None
        processes = self.repo.list_processes(status=ps, limit=limit)
        return [
            ProcessSummary(
                id=str(p.id),
                name=p.name,
                mode=p.mode.value,
                status=p.status.value,
                priority=p.priority,
                required_tags=p.required_tags,
                parent_process=str(p.parent_process) if p.parent_process else None,
            )
            for p in processes
        ]

    def get(self, name: str | None = None, id: str | None = None) -> ProcessHandle | ProcessError:
        """Get a process handle by name or id."""
        self._check("get")
        if id:
            proc = self.repo.get_process(UUID(id))
        elif name:
            proc = self.repo.get_process_by_name(name)
        else:
            return ProcessError(error="name or id is required")

        if proc is None:
            return ProcessError(error="process not found")

        # Look for spawn channels (if caller is parent or child)
        send_ch = self.repo.get_channel_by_name(f"spawn:{self.process_id}\u2192{proc.id}")
        recv_ch = self.repo.get_channel_by_name(f"spawn:{proc.id}\u2192{self.process_id}")

        # If no spawn channels, try implicit process channel for reading
        if recv_ch is None:
            recv_ch = self.repo.get_channel_by_name(f"process:{proc.name}")

        return ProcessHandle(
            repo=self.repo,
            caller_process_id=self.process_id,
            process=proc,
            send_channel=send_ch,
            recv_channel=recv_ch,
            run_id=self.run_id,
        )

    def _init_process_id(self) -> UUID | None:
        init = self.repo.get_process_by_name("init")
        return init.id if init else None

    def spawn(
        self,
        name: str,
        content: str = "",
        priority: float = 0.0,
        required_tags: list[str] | None = None,
        executor: str = "llm",
        model: str | None = None,
        capabilities: dict[str, "Capability | None"] | None = None,
        schema: dict | None = None,
        subscribe: str | list[str] | None = None,
        mode: str = "one_shot",
        idle_timeout_ms: int | None = None,
        detached: bool = False,
        tty: bool = False,
        wait_for: "list[ProcessHandle] | None" = None,
    ) -> ProcessHandle | ProcessError:
        """Spawn a child process. Capabilities are NOT inherited — pass them explicitly.

        capabilities is a dict mapping namespace name to capability instance:
            {"discord": discord, "email_me": email.scope(to=["x@y.com"])}
        Pass None as the value for unscoped full access by capability name lookup.
        """
        if not name:
            return ProcessError(error="name is required")

        self._check("spawn")

        if detached:
            init_id = self._init_process_id()
            parent_id = init_id if init_id else self.process_id
        else:
            parent_id = self.process_id

        proc_mode = ProcessMode(mode)
        # Deferred dispatch: process starts WAITING until targets exit.
        # Daemons start WAITING (activated by channel messages);
        # one-shots start RUNNABLE (run immediately).
        if wait_for:
            initial_status = ProcessStatus.WAITING
        elif proc_mode == ProcessMode.DAEMON:
            initial_status = ProcessStatus.WAITING
        else:
            initial_status = ProcessStatus.RUNNABLE
        # Inherit epoch from parent process
        parent_proc = self.repo.get_process(self.process_id)
        child_epoch = parent_proc.epoch if parent_proc else 0

        child = Process(
            name=name,
            mode=proc_mode,
            content=content,
            priority=priority,
            required_tags=required_tags or [],
            executor=executor,
            status=initial_status,
            parent_process=parent_id,
            model=model,
            idle_timeout_ms=idle_timeout_ms,
            tty=tty,
            epoch=child_epoch,
        )

        # Validate all capabilities before creating the process
        parent_grants = self.repo.list_process_capabilities(self.process_id)
        validated_caps: list[tuple[str, UUID, dict | None]] = []

        for grant_name, cap_instance in (capabilities or {}).items():
            if cap_instance is not None:
                # Unwrap tracing proxy to get the real capability
                real_instance = cap_instance
                try:
                    real_instance = object.__getattribute__(cap_instance, '_target')
                except AttributeError:
                    pass
                # Resolve the registered capability model from the instance
                cap_type_name = type(real_instance).__name__.lower().replace("capability", "")
                cap = self.repo.get_capability_by_name(cap_type_name)
                if not cap:
                    cap = self.repo.get_capability_by_name(grant_name)
                if not cap:
                    # Look up by handler class path
                    handler_path = f"{type(real_instance).__module__}.{type(real_instance).__name__}"
                    cap = self.repo.get_capability_by_handler(handler_path)
                child_scope = getattr(real_instance, "_scope", None) or None
            else:
                # Fallback: resolve capability type by grant name
                cap_type_name = grant_name
                cap = self.repo.get_capability_by_name(grant_name)
                child_scope = None

            if not cap or not cap.enabled:
                return ProcessError(error=f"Capability '{grant_name}' not found or disabled")

            matching_grants = [pg for pg in parent_grants if pg.capability == cap.id]
            if not matching_grants:
                return ProcessError(
                    error=f"Cannot delegate '{grant_name}': parent does not hold capability '{cap_type_name}'"
                )

            # Check if any parent grant allows the requested child scope
            delegation_ok = False
            for parent_grant in matching_grants:
                parent_scope = parent_grant.config
                if parent_scope and child_scope:
                    try:
                        narrowed = cap_instance._narrow(parent_scope, child_scope)
                        if narrowed == child_scope:
                            delegation_ok = True
                            break
                    except (ValueError, TypeError):
                        continue
                elif parent_scope and not child_scope:
                    continue  # can't widen, try next grant
                else:
                    delegation_ok = True
                    break

            if not delegation_ok:
                return ProcessError(
                    error=f"Cannot delegate '{grant_name}': child scope exceeds parent scope"
                )

            validated_caps.append((grant_name, cap.id, child_scope))

        # Validation passed — now create the process and bind capabilities.
        # Batch all writes to avoid per-write JSON serialization overhead.
        with self.repo.batch():
            return self._create_child(child, validated_caps, schema, subscribe, wait_for)

    def _create_child(
        self,
        child: Process,
        validated_caps: list[tuple[str, UUID, dict | None]],
        schema: dict | None,
        subscribe: str | list[str] | None,
        wait_for: list[ProcessHandle] | None = None,
    ) -> ProcessHandle | ProcessError:
        name = child.name
        child_epoch = child.epoch
        child_id = self.repo.upsert_process(child)

        for grant_name, cap_id, child_scope in validated_caps:
            pc = ProcessCapability(
                process=child_id,
                capability=cap_id,
                name=grant_name,
                config=child_scope,
            )
            self.repo.create_process_capability(pc)

        # Create spawn channels
        schema_id = None
        inline_schema = None
        if schema is not None:
            if isinstance(schema, dict):
                inline_schema = {"fields": schema} if "fields" not in schema else schema

        send_ch = Channel(
            name=f"spawn:{self.process_id}\u2192{child_id}",
            owner_process=self.process_id,
            channel_type=ChannelType.SPAWN,
            inline_schema=inline_schema,
            schema_id=schema_id,
        )
        self.repo.upsert_channel(send_ch)

        recv_ch = Channel(
            name=f"spawn:{child_id}\u2192{self.process_id}",
            owner_process=child_id,
            channel_type=ChannelType.SPAWN,
            inline_schema=inline_schema,
            schema_id=schema_id,
        )
        self.repo.upsert_channel(recv_ch)

        # Create per-process stdio channels (legacy names + coglet aliases)
        for stream in ("stdin", "stdout", "stderr"):
            io_ch = Channel(
                name=f"process:{name}:{stream}",
                owner_process=child_id,
                channel_type=ChannelType.NAMED,
            )
            self.repo.upsert_channel(io_ch)

        # Create coglet channel aliases (io:stdin, io:stdout, io:stderr, cog:from, cog:to)
        # These are the standard channels coglets use; they share the same underlying
        # message streams as the legacy process/spawn channels.
        stdout_schema = None
        if schema is not None:
            if isinstance(schema, dict):
                stdout_schema = {"fields": schema} if "fields" not in schema else schema
        for alias, _legacy in (
            (f"io:stdin:{name}", f"process:{name}:stdin"),
            (f"io:stdout:{name}", f"process:{name}:stdout"),
            (f"io:stderr:{name}", f"process:{name}:stderr"),
        ):
            alias_ch = Channel(
                name=alias,
                owner_process=child_id,
                channel_type=ChannelType.NAMED,
                inline_schema=stdout_schema if "stdout" in alias else None,
            )
            self.repo.upsert_channel(alias_ch)

        # cog:from = parent→child, cog:to = child→parent
        cog_from_ch = Channel(
            name=f"cog:from:{name}",
            owner_process=self.process_id,
            channel_type=ChannelType.NAMED,
        )
        self.repo.upsert_channel(cog_from_ch)
        cog_to_ch = Channel(
            name=f"cog:to:{name}",
            owner_process=child_id,
            channel_type=ChannelType.NAMED,
        )
        self.repo.upsert_channel(cog_to_ch)

        # Bind child to channel handlers if subscribe is set
        if subscribe:

            sub_list = [subscribe] if isinstance(subscribe, str) else subscribe
            for sub_name in sub_list:
                sub_ch = self.repo.get_channel_by_name(sub_name)
                if sub_ch is None:
                    return ProcessError(error=f"Subscribe channel '{sub_name}' not found")
                self.repo.create_handler(Handler(process=child_id, channel=sub_ch.id, epoch=child_epoch))

        # Deferred dispatch: create handlers + WAIT_ALL condition for target processes
        if wait_for:
            still_pending: list[str] = []
            for handle in wait_for:
                target_pid = UUID(handle.id)
                # Check if target already exited
                exit_ch = self.repo.get_channel_by_name(f"spawn:{target_pid}\u2192{self.process_id}")
                already_exited = False
                if exit_ch:
                    msgs = self.repo.list_channel_messages(exit_ch.id, limit=50)
                    already_exited = any(
                        isinstance(m.payload, dict) and m.payload.get("type") == "child:exited"
                        for m in msgs
                    )
                if not already_exited:
                    still_pending.append(handle.id)
                    if exit_ch:
                        self.repo.create_handler(Handler(process=child_id, channel=exit_ch.id, epoch=child_epoch))

            if still_pending:
                self.repo.create_wait_condition(WaitCondition(
                    process=child_id,
                    type=WaitConditionType.WAIT_ALL,
                    pending=still_pending,
                ))
            else:
                # All targets already exited — make process runnable immediately
                self.repo.update_process_status(child_id, ProcessStatus.RUNNABLE)

        child = self.repo.get_process(child_id)
        return ProcessHandle(
            repo=self.repo,
            caller_process_id=self.process_id,
            process=child,
            send_channel=send_ch,
            recv_channel=recv_ch,
            run_id=self.run_id,
        )

    def detach(self, process_id: str) -> ProcessDetail | ProcessError:
        """Reparent a child process to init (survives parent kill)."""
        self._check("detach")
        target = self.repo.get_process(UUID(process_id))
        if target is None:
            return ProcessError(error="process not found")
        init_id = self._init_process_id()
        if init_id is None:
            return ProcessError(error="init process not found")
        target.parent_process = init_id
        self.repo.upsert_process(target)
        return ProcessDetail(
            id=str(target.id), name=target.name, mode=target.mode.value,
            status=target.status.value, priority=target.priority, required_tags=target.required_tags,
            parent_process=str(init_id),
        )

    def __repr__(self) -> str:
        return "<ProcsCapability list() get() spawn() detach()>"

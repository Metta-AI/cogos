"""Process capabilities — list, get, and spawn processes."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.process_handle import ProcessHandle
from cogos.db.models import Channel, ChannelType, Process, ProcessCapability, ProcessMode, ProcessStatus

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class ProcessSummary(BaseModel):
    id: str
    name: str
    mode: str
    status: str
    priority: float
    runner: str
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

    ALL_OPS = {"list", "get", "spawn"}

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
                runner=p.runner,
                parent_process=str(p.parent_process) if p.parent_process else None,
            )
            for p in processes
        ]

    def get(self, name: str | None = None, id: str | None = None) -> ProcessHandle | ProcessError:
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
        )

    def spawn(
        self,
        name: str,
        content: str = "",
        priority: float = 0.0,
        runner: str = "lambda",
        model: str | None = None,
        capabilities: dict[str, "Capability | None"] | None = None,
        schema: dict | None = None,
    ) -> ProcessHandle | ProcessError:
        """Spawn a child process. Capabilities are NOT inherited — pass them explicitly.

        capabilities is a dict mapping namespace name to capability instance:
            {"discord": discord, "email_me": email.scope(to=["x@y.com"])}
        Pass None as the value for unscoped full access by capability name lookup.
        """
        if not name:
            return ProcessError(error="name is required")

        self._check("spawn")

        child = Process(
            name=name,
            mode=ProcessMode.ONE_SHOT,
            content=content,
            priority=priority,
            runner=runner,
            status=ProcessStatus.RUNNABLE,
            parent_process=self.process_id,
            model=model,
        )

        child_id = self.repo.upsert_process(child)

        # Bind explicitly requested capabilities (with delegation authorization)
        parent_grants = self.repo.list_process_capabilities(self.process_id)

        for grant_name, cap_instance in (capabilities or {}).items():
            if cap_instance is not None:
                # Scoped or unscoped capability instance — resolve by class name
                cap_type_name = type(cap_instance).__name__.lower().replace("capability", "")
                cap = self.repo.get_capability_by_name(cap_type_name)
                child_scope = getattr(cap_instance, "_scope", None) or None
            else:
                # None means look up by grant_name, unscoped
                cap_type_name = grant_name
                cap = self.repo.get_capability_by_name(grant_name)
                child_scope = None

            if not cap or not cap.enabled:
                return ProcessError(error=f"Capability '{grant_name}' not found or disabled")

            # Check parent holds this capability type
            parent_grant = next(
                (pg for pg in parent_grants if pg.capability == cap.id),
                None,
            )
            if parent_grant is None:
                return ProcessError(
                    error=f"Cannot delegate '{grant_name}': parent does not hold capability '{cap_type_name}'"
                )

            # Check child scope is within parent scope
            parent_scope = parent_grant.config
            if parent_scope and child_scope:
                try:
                    narrowed = cap_instance._narrow(parent_scope, child_scope)
                    if narrowed != child_scope:
                        return ProcessError(
                            error=f"Cannot delegate '{grant_name}': child scope exceeds parent scope"
                        )
                except (ValueError, TypeError):
                    return ProcessError(
                        error=f"Cannot delegate '{grant_name}': child scope exceeds parent scope"
                    )
            elif parent_scope and not child_scope:
                # Parent is scoped but child is unscoped = widening = denied
                return ProcessError(
                    error=f"Cannot delegate '{grant_name}': cannot widen parent's scoped grant to unscoped"
                )
            # If parent is unscoped, child can be anything (narrowing is always OK)

            pc = ProcessCapability(
                process=child_id,
                capability=cap.id,
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

        child = self.repo.get_process(child_id)
        return ProcessHandle(
            repo=self.repo,
            caller_process_id=self.process_id,
            process=child,
            send_channel=send_ch,
            recv_channel=recv_ch,
        )

    def __repr__(self) -> str:
        return "<ProcsCapability list() get() spawn()>"

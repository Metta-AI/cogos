"""Process capabilities — list, get, and spawn processes."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.db.models import Process, ProcessCapability, ProcessMode, ProcessStatus

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

    def get(self, name: str | None = None, id: str | None = None) -> ProcessDetail | ProcessError:
        self._check("get")
        if id:
            proc = self.repo.get_process(UUID(id))
        elif name:
            proc = self.repo.get_process_by_name(name)
        else:
            return ProcessError(error="name or id is required")

        if proc is None:
            return ProcessError(error="process not found")

        return ProcessDetail(
            id=str(proc.id),
            name=proc.name,
            mode=proc.mode.value,
            status=proc.status.value,
            priority=proc.priority,
            runner=proc.runner,
            content=proc.content,
            code=str(proc.code) if proc.code else None,
            parent_process=str(proc.parent_process) if proc.parent_process else None,
            preemptible=proc.preemptible,
            model=proc.model,
            max_retries=proc.max_retries,
            retry_count=proc.retry_count,
            created_at=proc.created_at.isoformat() if proc.created_at else None,
            updated_at=proc.updated_at.isoformat() if proc.updated_at else None,
        )

    def spawn(
        self,
        name: str,
        content: str = "",
        code: str | None = None,
        priority: float = 0.0,
        runner: str = "lambda",
        model: str | None = None,
        capabilities: dict[str, "Capability | None"] | None = None,
    ) -> SpawnResult | ProcessError:
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
            code=UUID(code) if code else None,
            priority=priority,
            runner=runner,
            status=ProcessStatus.RUNNABLE,
            parent_process=self.process_id,
            model=model,
        )

        child_id = self.repo.upsert_process(child)

        # Bind explicitly requested capabilities
        for grant_name, cap_instance in (capabilities or {}).items():
            if cap_instance is not None:
                # Scoped or unscoped capability instance — resolve by class name
                cap_type_name = type(cap_instance).__name__.lower().replace("capability", "")
                cap = self.repo.get_capability_by_name(cap_type_name)
                scope_config = getattr(cap_instance, "_scope", None) or None
            else:
                # None means look up by grant_name, unscoped
                cap = self.repo.get_capability_by_name(grant_name)
                scope_config = None

            if cap and cap.enabled:
                pc = ProcessCapability(
                    process=child_id,
                    capability=cap.id,
                    name=grant_name,
                    config=scope_config,
                )
                self.repo.create_process_capability(pc)
            else:
                logger.warning("Capability for grant %r not found or disabled, skipping", grant_name)

        return SpawnResult(
            id=str(child_id),
            name=name,
            status=ProcessStatus.RUNNABLE.value,
            parent_process=str(self.process_id),
        )

    def __repr__(self) -> str:
        return "<ProcsCapability list() get() spawn()>"

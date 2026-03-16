"""CogletRuntimeCapability — run, list, and stop coglet processes."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.cog import (
    Coglet,
    CogletError,
    load_coglet_meta,
    read_file_tree,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CogletRun — handle for a running coglet
# ---------------------------------------------------------------------------

class CogletRun:
    """Handle for a running coglet. Wraps a ProcessHandle."""

    def __init__(self, process_handle) -> None:
        self._handle = process_handle

    def process(self):
        """Return the underlying ProcessHandle."""
        return self._handle

    def __repr__(self) -> str:
        return f"<CogletRun process={self._handle.id}>"


# ---------------------------------------------------------------------------
# IO Models
# ---------------------------------------------------------------------------

class CogletRunInfo(BaseModel):
    cog_name: str
    coglet_name: str
    process_id: str
    status: str


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

class CogletRuntimeCapability(Capability):
    """Run coglets as CogOS processes.

    Usage:
        run = coglet_runtime.run(coglet, capability_overrides={...})
        child = run.process()
        coglet_runtime.list()
        coglet_runtime.stop(run)
    """

    ALL_OPS = {"run", "list", "stop"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})")

    def run(
        self,
        coglet: Coglet,
        procs,
        capability_overrides: dict | None = None,
        subscribe: str | None = None,
    ) -> CogletRun | CogletError:
        """Run a coglet as a CogOS process. Returns CogletRun or error."""
        self._check("run")
        store = FileStore(self.repo)

        meta = load_coglet_meta(store, coglet.cog_name, coglet.name)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet.name}' not found in cog '{coglet.cog_name}'")

        if not meta.entrypoint:
            return CogletError(error=f"Coglet '{coglet.name}' has no entrypoint (data-only coglet)")

        main_files = read_file_tree(store, coglet.cog_name, coglet.name, "main")
        content = main_files.get(meta.entrypoint)
        if content is None:
            return CogletError(error=f"Entrypoint '{meta.entrypoint}' not found in coglet '{coglet.name}'")

        # Merge capabilities: meta defaults + overrides
        spawn_caps = {}
        for cap_entry in meta.capabilities:
            if isinstance(cap_entry, dict):
                alias = cap_entry.get("alias", cap_entry["name"])
                spawn_caps[alias] = None
            else:
                spawn_caps[cap_entry] = None
        if capability_overrides:
            spawn_caps.update(capability_overrides)

        handle = procs.spawn(
            name=f"{coglet.cog_name}/{coglet.name}",
            content=content,
            mode=meta.mode,
            model=meta.model,
            capabilities=spawn_caps,
            subscribe=subscribe,
            idle_timeout_ms=meta.idle_timeout_ms,
        )

        # procs.spawn can return ProcessError
        from cogos.capabilities.procs import ProcessError
        if isinstance(handle, ProcessError):
            return CogletError(error=f"Failed to spawn: {handle.error}")

        return CogletRun(handle)

    def __repr__(self) -> str:
        return "<CogletRuntimeCapability run() list() stop()>"

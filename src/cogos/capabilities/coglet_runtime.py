"""CogletRuntime capability — runs coglets as processes."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from cogos.capabilities.base import Capability
from cogos.cog.runtime import CogletManifest

logger = logging.getLogger(__name__)


class CogletRuntimeCapability(Capability):
    """Run coglets as CogOS processes.

    Usage:
        result = coglet_runtime.run(coglet, procs, capabilities={...})
    """

    ALL_OPS = {"run"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        if "ops" in existing and "ops" in requested:
            merged["ops"] = existing["ops"] & requested["ops"]
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")

    def run(
        self,
        coglet: CogletManifest,
        procs: Any,
        capabilities: dict | None = None,
    ) -> Any:
        """Run a coglet manifest as a process. Returns ProcessHandle.

        Spawns the coglet as a child process via procs.spawn().
        If capabilities is provided, those are granted to the worker.
        """
        self._check("run")

        caps = dict(capabilities) if capabilities else {}

        return procs.spawn(
            name=coglet.name,
            content=coglet.content,
            mode=coglet.config.mode,
            priority=coglet.config.priority,
            executor=coglet.config.executor,
            model=coglet.config.model,
            runner=coglet.config.runner,
            idle_timeout_ms=coglet.config.idle_timeout_ms,
            capabilities=caps,
        )

    def __repr__(self) -> str:
        return "<CogletRuntimeCapability run(coglet, procs, capabilities?)>"

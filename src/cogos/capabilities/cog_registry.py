"""CogRegistry capability — access to Cog objects for dynamic coglet creation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cogos.capabilities.base import Capability
from cogos.cog.cog import Cog

logger = logging.getLogger(__name__)


class CogRegistryCapability(Capability):
    """Registry of loaded Cog objects.

    Usage:
        worker = cog_registry.get_or_make_cog("cogos/worker")
        coglet, caps = worker.make_coglet("do something")
    """

    ALL_OPS = {"get"}

    def __init__(self, repo, process_id, run_id=None, trace_id=None, base_dir=None):
        super().__init__(repo, process_id, run_id=run_id, trace_id=trace_id)
        self._base_dir = Path(base_dir) if base_dir else None
        self._cache: dict[str, Cog] = {}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        if "paths" in existing and "paths" in requested:
            merged["paths"] = [p for p in requested["paths"] if p in existing["paths"]]
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        allowed_paths = self._scope.get("paths")
        if allowed_paths is not None:
            path = str(context.get("path", ""))
            if not any(path.startswith(p) for p in allowed_paths):
                raise PermissionError(f"Path '{path}' not in allowed paths")

    def get_or_make_cog(self, path: str) -> Cog:
        """Load a Cog from the given path (relative to base_dir)."""
        self._check("get", path=path)
        if path in self._cache:
            return self._cache[path]

        if self._base_dir is not None:
            full_path = self._base_dir / path
        else:
            full_path = Path(path)

        cog = Cog(full_path)
        self._cache[path] = cog
        return cog

    def __repr__(self) -> str:
        return "<CogRegistryCapability get_or_make_cog(path)>"

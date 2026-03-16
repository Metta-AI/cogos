"""CogCapability — scoped factory that makes coglets within a cog."""

from __future__ import annotations

import logging

from cogos.capabilities.base import Capability
from cogos.cog import (
    Coglet,
    CogletError,
    CogletInfo,
    CogMeta,
    load_cog_meta,
    load_coglet_meta,
    save_cog_meta,
    save_coglet_meta,
    write_file_tree,
)
from cogos.coglet import CogletMeta, run_tests
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


class CogCapability(Capability):
    """Make coglets within a cog.

    Must be scoped with a cog_name before use.

    Usage:
        coglet = cog.make_coglet("discover", test_command="true",
                                  files={"main.md": content},
                                  entrypoint="main.md", mode="one_shot")
    """

    ALL_OPS = {"make_coglet"}

    def _cog_name(self) -> str:
        name = self._scope.get("cog_name")
        if not name:
            raise PermissionError("CogCapability requires cog_name in scope")
        return name

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)

        old_name = existing.get("cog_name")
        new_name = requested.get("cog_name")
        if old_name is not None and new_name is not None and old_name != new_name:
            raise ValueError(f"Cannot change cog_name from '{old_name}' to '{new_name}'")
        result["cog_name"] = old_name or new_name
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})")

    def make_coglet(
        self,
        name: str,
        test_command: str = "true",
        files: dict[str, str] | None = None,
        entrypoint: str | None = None,
        mode: str = "one_shot",
        model: str | None = None,
        capabilities: list | None = None,
        idle_timeout_ms: int | None = None,
    ) -> Coglet | CogletError:
        """Create or update a coglet in this cog. Returns the Coglet object."""
        self._check("make_coglet")
        cog_name = self._cog_name()
        store = FileStore(self.repo)
        files = files or {}

        # Ensure cog meta exists
        cog_meta = load_cog_meta(store, cog_name)
        if cog_meta is None:
            save_cog_meta(store, cog_name, CogMeta(name=cog_name))

        # Check if coglet already exists
        existing = load_coglet_meta(store, cog_name, name)
        if existing is not None:
            # Update existing coglet
            existing.test_command = test_command
            existing.entrypoint = entrypoint
            existing.mode = mode
            existing.model = model
            existing.capabilities = capabilities or []
            existing.idle_timeout_ms = idle_timeout_ms
            write_file_tree(store, cog_name, name, "main", files)
            save_coglet_meta(store, cog_name, name, existing)
        else:
            # Create new coglet
            meta = CogletMeta(
                name=name,
                test_command=test_command,
                entrypoint=entrypoint,
                mode=mode,
                model=model,
                capabilities=capabilities or [],
                idle_timeout_ms=idle_timeout_ms,
            )
            write_file_tree(store, cog_name, name, "main", files)
            save_coglet_meta(store, cog_name, name, meta)

        return Coglet(self.repo, cog_name, name)

    def __repr__(self) -> str:
        cog = self._scope.get("cog_name", "?")
        return f"<CogCapability cog={cog} make_coglet()>"

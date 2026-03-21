"""CogRegistry capability — access to Cog objects for dynamic coglet creation."""

from __future__ import annotations

import logging
from typing import Any

from cogos.capabilities.base import Capability
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


class CogProxy:
    """Lightweight cog wrapper that reads files from FileStore.

    Supports make_coglet(reason) by loading and executing make_coglet.py
    from the FileStore.
    """

    def __init__(self, name: str, prefix: str, file_store: FileStore) -> None:
        self.name = name
        self._prefix = prefix  # e.g. "cogos/worker"
        self._fs = file_store

    def _read(self, filename: str) -> str | None:
        """Read a file from this cog's directory in FileStore."""
        key = f"{self._prefix}/{filename}"
        return self._fs.get_content(key)

    def make_coglet(self, reason: str) -> tuple:
        """Create a dynamic coglet via this cog's make_coglet.py.

        Returns (CogletManifest, required_capabilities).
        """
        code = self._read("make_coglet.py")
        if not code:
            raise FileNotFoundError(
                f"Cog '{self.name}' does not support make_coglet "
                f"(no {self._prefix}/make_coglet.py in FileStore)"
            )

        # Create a helper that reads files from FileStore (used by make_coglet.py)
        fs = self._fs
        prefix = self._prefix

        class _CogDir:
            """Path-like object that reads from FileStore instead of filesystem."""
            def __init__(self, base: str):
                self._base = base

            def __truediv__(self, other: str):
                return _CogDir(self._base + "/" + other)

            def read_text(self) -> str:
                content = fs.get_content(self._base)
                return content or ""

            def exists(self) -> bool:
                return fs.get_content(self._base) is not None

        cog_dir = _CogDir(prefix)

        # Execute make_coglet.py
        ns: dict[str, Any] = {}
        exec(compile(code, f"{prefix}/make_coglet.py", "exec"), ns)  # noqa: S102
        fn = ns.get("make_coglet")
        if fn is None:
            raise ValueError(f"{prefix}/make_coglet.py does not define make_coglet()")
        return fn(reason, cog_dir=cog_dir)

    def __repr__(self) -> str:
        return f"<Cog '{self.name}' make_coglet(reason)>"


class CogRegistryCapability(Capability):
    """Registry of cog objects loaded from FileStore.

    Usage:
        worker = cog_registry.get_or_make_cog("cogos/worker")
        coglet, caps = worker.make_coglet("do something")
    """

    ALL_OPS = {"get"}

    def __init__(self, repo, process_id, run_id=None, trace_id=None):
        super().__init__(repo, process_id, run_id=run_id, trace_id=trace_id)
        self._cache: dict[str, CogProxy] = {}

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

    def get_or_make_cog(self, path: str) -> CogProxy:
        """Load a cog from FileStore by path prefix (e.g. 'cogos/worker')."""
        self._check("get", path=path)
        if path in self._cache:
            return self._cache[path]

        fs = FileStore(self.repo)
        name = path.rstrip("/").split("/")[-1]
        proxy = CogProxy(name=name, prefix=path.rstrip("/"), file_store=fs)
        self._cache[path] = proxy
        return proxy

    def __repr__(self) -> str:
        return "<CogRegistryCapability get_or_make_cog(path)>"

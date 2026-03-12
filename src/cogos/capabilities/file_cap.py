"""Fine-grained file capabilities — single-file and directory-scoped access."""

from __future__ import annotations

import logging

from cogos.capabilities.base import Capability
from cogos.capabilities.files import (
    FileContent,
    FileError,
    FileSearchResult,
    FileWriteResult,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ── FileCapability ──────────────────────────────────────────


class FileCapability(Capability):
    """Access to a single file by key.

    Usage:
        file.read("/config/system")
        file.write("/config/system", "new content")
    """

    ALL_OPS = {"read", "write", "delete", "get_metadata"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        # Key cannot change once set
        if "key" in existing and "key" in requested:
            if requested["key"] != existing["key"]:
                raise ValueError(
                    f"Cannot change scoped key from {existing['key']!r} "
                    f"to {requested['key']!r}"
                )
            merged["key"] = existing["key"]
        # Ops narrowing: intersection
        if "ops" in existing and "ops" in requested:
            merged["ops"] = existing["ops"] & requested["ops"]
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        # Check ops
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        # Check key
        scoped_key = self._scope.get("key")
        if scoped_key is not None:
            key = context.get("key", "")
            if str(key) != scoped_key:
                raise PermissionError(
                    f"Key {key!r} does not match scoped key {scoped_key!r}"
                )

    def read(self, key: str) -> FileContent | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("read", key=key)

        store = FileStore(self.repo)
        f = store.get(key)
        if f is None:
            return FileError(error=f"file '{key}' not found")

        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{key}'")

        return FileContent(
            id=str(f.id),
            key=f.key,
            version=fv.version,
            content=fv.content,
            read_only=fv.read_only,
            source=fv.source,
        )

    def write(
        self, key: str, content: str, source: str = "agent"
    ) -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)

        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)

        if result is None:
            return FileWriteResult(
                id="", key=key, version=0, created=False, changed=False
            )

        from cogos.db.models import File

        if isinstance(result, File):
            return FileWriteResult(
                id=str(result.id), key=key, version=1, created=True
            )

        return FileWriteResult(
            id=str(result.file_id), key=key, version=result.version, created=False
        )

    def __repr__(self) -> str:
        return "<FileCapability read() write()>"


# ── FileVersionCapability ───────────────────────────────────


class FileVersionCapability(Capability):
    """Access to versions of a single file.

    Usage:
        file_version.add("/config/system", "new content")
        file_version.list("/config/system")
    """

    ALL_OPS = {"add", "list", "get", "update"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        # Key cannot change once set
        if "key" in existing and "key" in requested:
            if requested["key"] != existing["key"]:
                raise ValueError(
                    f"Cannot change scoped key from {existing['key']!r} "
                    f"to {requested['key']!r}"
                )
            merged["key"] = existing["key"]
        # Ops narrowing: intersection
        if "ops" in existing and "ops" in requested:
            merged["ops"] = existing["ops"] & requested["ops"]
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        # Check ops
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        # Check key
        scoped_key = self._scope.get("key")
        if scoped_key is not None:
            key = context.get("key", "")
            if str(key) != scoped_key:
                raise PermissionError(
                    f"Key {key!r} does not match scoped key {scoped_key!r}"
                )

    def add(
        self, key: str, content: str, source: str = "agent"
    ) -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("add", key=key)

        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)

        if result is None:
            return FileWriteResult(
                id="", key=key, version=0, created=False, changed=False
            )

        from cogos.db.models import File

        if isinstance(result, File):
            return FileWriteResult(
                id=str(result.id), key=key, version=1, created=True
            )

        return FileWriteResult(
            id=str(result.file_id), key=key, version=result.version, created=False
        )

    def list(self, key: str) -> list[FileContent]:
        if not key:
            return []
        self._check("list", key=key)

        store = FileStore(self.repo)
        versions = store.history(key)
        return [
            FileContent(
                id=str(fv.file_id),
                key=key,
                version=fv.version,
                content=fv.content,
                read_only=fv.read_only,
                source=fv.source,
            )
            for fv in versions
        ]

    def __repr__(self) -> str:
        return "<FileVersionCapability add() list()>"


# ── DirCapability ───────────────────────────────────────────


class DirCapability(Capability):
    """Access to files under a directory prefix.

    Usage:
        dir.list()
        dir.read("/workspace/file.txt")
        dir.write("/workspace/file.txt", "content")
    """

    ALL_OPS = {"list", "read", "write", "create", "delete"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        # Prefix narrowing: new prefix must start with old prefix
        if "prefix" in existing and "prefix" in requested:
            if not requested["prefix"].startswith(existing["prefix"]):
                raise ValueError(
                    f"Cannot widen prefix from {existing['prefix']!r} "
                    f"to {requested['prefix']!r}"
                )
            merged["prefix"] = requested["prefix"]
        # Ops narrowing: intersection
        if "ops" in existing and "ops" in requested:
            merged["ops"] = existing["ops"] & requested["ops"]
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        # Check ops
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")
        # Check prefix
        prefix = self._scope.get("prefix")
        if prefix is not None:
            key = context.get("key", "")
            if key and not str(key).startswith(prefix):
                raise PermissionError(
                    f"Key {key!r} outside allowed prefix {prefix!r}"
                )

    def list(
        self, prefix: str | None = None, limit: int = 50
    ) -> list[FileSearchResult]:
        # Use the scoped prefix if no explicit prefix given
        effective_prefix = prefix or self._scope.get("prefix")
        self._check("list", key=effective_prefix or "")

        store = FileStore(self.repo)
        files = store.list_files(prefix=effective_prefix, limit=limit)
        return [FileSearchResult(id=str(f.id), key=f.key) for f in files]

    def read(self, key: str) -> FileContent | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("read", key=key)

        store = FileStore(self.repo)
        f = store.get(key)
        if f is None:
            return FileError(error=f"file '{key}' not found")

        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{key}'")

        return FileContent(
            id=str(f.id),
            key=f.key,
            version=fv.version,
            content=fv.content,
            read_only=fv.read_only,
            source=fv.source,
        )

    def write(
        self, key: str, content: str, source: str = "agent"
    ) -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)

        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source)

        if result is None:
            return FileWriteResult(
                id="", key=key, version=0, created=False, changed=False
            )

        from cogos.db.models import File

        if isinstance(result, File):
            return FileWriteResult(
                id=str(result.id), key=key, version=1, created=True
            )

        return FileWriteResult(
            id=str(result.file_id), key=key, version=result.version, created=False
        )

    def __repr__(self) -> str:
        return "<DirCapability list() read() write()>"

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
        f = dir.get("path/to/file.txt")
        f.read()        -> FileContent
        f.write(content) -> FileWriteResult
        f.append(text)   -> FileWriteResult
    """

    ALL_OPS = {"read", "write", "append", "delete", "get_metadata"}

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

    def _resolve_key(self, key: str | None = None) -> str:
        """Return the effective key — explicit arg or scoped key."""
        k = key or self._scope.get("key")
        if not k:
            raise ValueError("key is required (pass it or scope the capability)")
        return k

    def read(self, key: str | None = None) -> FileContent | FileError:
        k = self._resolve_key(key)
        self._check("read", key=k)

        store = FileStore(self.repo)
        f = store.get(k)
        if f is None:
            return FileError(error=f"file '{k}' not found")

        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{k}'")

        return FileContent(
            id=str(f.id),
            key=f.key,
            version=fv.version,
            content=fv.content,
            read_only=fv.read_only,
            source=fv.source,
        )

    def write(
        self, content: str, key: str | None = None, source: str = "agent"
    ) -> FileWriteResult | FileError:
        k = self._resolve_key(key)
        self._check("write", key=k)
        return self._do_write(k, content, source)

    def append(
        self, content: str, key: str | None = None, source: str = "agent"
    ) -> FileWriteResult | FileError:
        """Append content to the file's active version in-place. Creates the file if it doesn't exist."""
        k = self._resolve_key(key)
        self._check("append", key=k)

        store = FileStore(self.repo)
        result = store.append(k, content, source=source)

        if result is None:
            return FileWriteResult(
                id="", key=k, version=0, created=False, changed=False
            )

        from cogos.db.models import File

        if isinstance(result, File):
            return FileWriteResult(
                id=str(result.id), key=k, version=1, created=True
            )

        return FileWriteResult(
            id=str(result.file_id), key=k, version=result.version, created=False
        )

    def _do_write(
        self, key: str, content: str, source: str
    ) -> FileWriteResult | FileError:
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
        k = self._scope.get("key", "")
        if k:
            return f"<File '{k}' read() write() append()>"
        return "<FileCapability read(key) write(content, key) append(content, key)>"


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

    def add(self, key: str, content: str, source: str = "agent"):
        self._check("add", key=key)
        store = FileStore(self.repo)
        return store.upsert(key, content, source=source)

    def list(self, key: str, limit: int = 50):
        self._check("list", key=key)
        f = FileStore(self.repo).get(key)
        if f is None:
            return FileError(error=f"file '{key}' not found")
        versions = self.repo.list_file_versions(f.id, limit=limit)
        return [{"version": v.version, "content": v.content[:200]} for v in versions]


# ── DirCapability ───────────────────────────────────────────


class DirCapability(Capability):
    """Directory access — list files and get file handles.

    Usage:
        dir.list()                 -> list of file keys
        f = dir.get("file.txt")   -> FileCapability scoped to that key
        f.read()                   -> file content
        f.write("new content")     -> overwrite
        f.append("more text")      -> append to file
    """

    ALL_OPS = {"list", "get"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        if "prefix" in existing and "prefix" in requested:
            if not requested["prefix"].startswith(existing["prefix"]):
                raise ValueError(
                    f"Cannot widen prefix from {existing['prefix']!r} "
                    f"to {requested['prefix']!r}"
                )
            merged["prefix"] = requested["prefix"]
        return merged

    def _full_key(self, key: str) -> str:
        """Prepend the scoped prefix to a relative key."""
        prefix = self._scope.get("prefix", "")
        if prefix and not key.startswith(prefix):
            return prefix.rstrip("/") + "/" + key.lstrip("/")
        return key

    def list(
        self, prefix: str | None = None, limit: int = 50
    ) -> list[FileSearchResult]:
        effective_prefix = self._full_key(prefix) if prefix else self._scope.get("prefix")

        store = FileStore(self.repo)
        files = store.list_files(prefix=effective_prefix, limit=limit)
        return [FileSearchResult(id=str(f.id), key=f.key) for f in files]

    def get(self, key: str) -> FileCapability:
        """Return a FileCapability scoped to the given key under this dir."""
        full_key = self._full_key(key)
        fc = FileCapability(
            repo=self.repo,
            process_id=self.process_id,
            run_id=self.run_id,
        )
        fc._scope = {"key": full_key}
        return fc

    def __repr__(self) -> str:
        prefix = self._scope.get("prefix", "")
        if prefix:
            return f"<Dir '{prefix}' list() get(key)>"
        return "<DirCapability list() get(key)>"

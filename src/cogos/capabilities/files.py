"""File capabilities — read, write, search files in the versioned store."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class FileContent(BaseModel):
    id: str
    key: str
    version: int
    content: str
    read_only: bool = False
    source: str = ""
    total_lines: int | None = None


class FileWriteResult(BaseModel):
    id: str
    key: str
    version: int
    created: bool
    changed: bool = True


class FileSearchResult(BaseModel):
    id: str
    key: str


class FileError(BaseModel):
    error: str


class GrepMatch(BaseModel):
    line: int
    text: str
    before: list[str] = []
    after: list[str] = []


class GrepResult(BaseModel):
    key: str
    matches: list[GrepMatch]


# ── Capability ───────────────────────────────────────────────


class FilesCapability(Capability):
    """Versioned file store.

    Usage:
        files.read("config/system")
        files.write("notes/daily", "today's notes")
        files.search("config/")
    """

    ALL_OPS = {"read", "write", "search"}

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
            if not str(key).startswith(prefix):
                raise PermissionError(
                    f"Key {key!r} outside allowed prefix {prefix!r}"
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
        self,
        key: str,
        content: str,
        source: str = "agent",
        read_only: bool = False,
    ) -> FileWriteResult | FileError:
        if not key:
            return FileError(error="key is required")
        self._check("write", key=key)

        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source, read_only=read_only, run_id=self.run_id)

        if result is None:
            return FileWriteResult(id="", key=key, version=0, created=False, changed=False)

        from cogos.db.models import File

        if isinstance(result, File):
            return FileWriteResult(id=str(result.id), key=key, version=1, created=True)

        return FileWriteResult(id=str(result.file_id), key=key, version=result.version, created=False)

    def search(self, prefix: str | None = None, limit: int = 50) -> list[FileSearchResult]:
        self._check("search", key=prefix or "")
        store = FileStore(self.repo)
        files = store.list_files(prefix=prefix, limit=limit)
        return [FileSearchResult(id=str(f.id), key=f.key) for f in files]

    def __repr__(self) -> str:
        return "<FilesCapability read() write() search()>"

"""Fine-grained file capabilities — single-file and directory-scoped access."""

from __future__ import annotations

import logging

from cogos.capabilities.base import Capability
from cogos.capabilities.files import (
    FileContent,
    FileError,
    FileSearchResult,
    FileWriteResult,
    GrepMatch,
    GrepResult,
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

    ALL_OPS = {"read", "write", "append", "edit"}

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

    def read(
        self,
        key: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> FileContent | FileError:
        """Read file content. Supports offset/limit for partial reads."""
        k = self._resolve_key(key)
        self._check("read", key=k)

        store = FileStore(self.repo)
        f = store.get(k)
        if f is None:
            return FileError(error=f"file '{k}' not found")

        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{k}'")

        content = fv.content
        lines = content.split("\n")
        total_lines = len(lines)

        if offset is not None or limit is not None:
            start = offset or 0
            if start < 0:
                start = max(0, total_lines + start)
            end = start + limit if limit is not None else total_lines
            content = "\n".join(lines[start:end])

        return FileContent(
            id=str(f.id),
            key=f.key,
            version=fv.version,
            content=content,
            read_only=fv.read_only,
            source=fv.source,
            total_lines=total_lines,
        )

    def head(self, key: str | None = None, n: int = 20) -> FileContent | FileError:
        """First n lines of a file."""
        return self.read(key, offset=0, limit=n)

    def tail(self, key: str | None = None, n: int = 20) -> FileContent | FileError:
        """Last n lines of a file."""
        return self.read(key, offset=-n)

    def write(
        self, content: str, key: str | None = None, source: str = "agent"
    ) -> FileWriteResult | FileError:
        """Overwrite the file with new content."""
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
        result = store.append(k, content, source=source, run_id=self.run_id)

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

    def edit(
        self,
        key: str | None = None,
        old: str = "",
        new: str = "",
        replace_all: bool = False,
        source: str = "agent",
    ) -> FileWriteResult | FileError:
        """Surgical string replacement. Fails if old not found or not unique (unless replace_all)."""
        k = self._resolve_key(key)
        self._check("edit", key=k)

        store = FileStore(self.repo)
        f = store.get(k)
        if f is None:
            return FileError(error=f"file '{k}' not found")

        fv = self.repo.get_active_file_version(f.id)
        if fv is None:
            return FileError(error=f"no active version for '{k}'")

        content = fv.content
        count = content.count(old)

        if count == 0:
            return FileError(error=f"old string not found in '{k}'")

        if not replace_all and count > 1:
            return FileError(error=f"old string not unique in '{k}' ({count} occurrences)")

        if replace_all:
            new_content = content.replace(old, new)
        else:
            new_content = content.replace(old, new, 1)

        return self._do_write(k, new_content, source)

    def _do_write(
        self, key: str, content: str, source: str
    ) -> FileWriteResult | FileError:
        store = FileStore(self.repo)
        result = store.upsert(key, content, source=source, run_id=self.run_id)

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
            return f"<File '{k}' read() write() append() edit()>"
        return "<FileCapability read(key) write(content, key) append(content, key) edit(key, old, new)>"


# ── FileVersionCapability ───────────────────────────────────


class FileVersionCapability(Capability):
    """Access to versions of a single file.

    Usage:
        file_version.add("/config/system", "new content")
        file_version.list("/config/system")
    """

    ALL_OPS = {"add", "list"}

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
        """Create a new version of a file."""
        self._check("add", key=key)
        store = FileStore(self.repo)
        return store.upsert(key, content, source=source, run_id=self.run_id)

    def list(self, key: str, limit: int = 50):
        """List versions of a file."""
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

    ALL_OPS = {"list", "get", "grep", "glob", "tree"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {**existing, **requested}
        if "prefix" in existing and "prefix" in requested:
            if not requested["prefix"].startswith(existing["prefix"]):
                raise ValueError(
                    f"Cannot widen prefix from {existing['prefix']!r} "
                    f"to {requested['prefix']!r}"
                )
            merged["prefix"] = requested["prefix"]
        # read_only is sticky — once True, cannot be set back to False
        if existing.get("read_only"):
            merged["read_only"] = True
        return merged

    def _full_key(self, key: str) -> str:
        """Prepend the scoped prefix to a relative key."""
        prefix = self._scope.get("prefix", "")
        if prefix and not key.startswith(prefix):
            return prefix.rstrip("/") + "/" + key.lstrip("/")
        return key

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not permitted")

    def list(
        self, prefix: str | None = None, limit: int = 50
    ) -> list[FileSearchResult]:
        """List files under this directory."""
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
        scope: dict = {"key": full_key}
        if self._scope.get("read_only"):
            scope["ops"] = {"read"}
        fc._scope = scope
        return fc

    def grep(
        self,
        pattern: str,
        prefix: str | None = None,
        limit: int = 20,
        context: int = 0,
    ) -> list[GrepResult]:
        """Regex search across file contents. Returns keys + matching lines."""
        self._check("grep")
        effective_prefix = (
            self._full_key(prefix) if prefix else self._scope.get("prefix")
        )
        raw = self.repo.grep_files(pattern, prefix=effective_prefix, limit=100)

        import re

        results: list[GrepResult] = []
        total_matches = 0
        for key, content in raw:
            if total_matches >= limit:
                break
            lines = content.split("\n")
            matches: list[GrepMatch] = []
            for i, line in enumerate(lines):
                if total_matches >= limit:
                    break
                if re.search(pattern, line):
                    before = lines[max(0, i - context) : i] if context > 0 else []
                    after = (
                        lines[i + 1 : i + 1 + context] if context > 0 else []
                    )
                    matches.append(
                        GrepMatch(line=i, text=line, before=before, after=after)
                    )
                    total_matches += 1
            if matches:
                results.append(GrepResult(key=key, matches=matches))
        return results

    def glob(
        self,
        pattern: str,
        limit: int = 50,
    ) -> list[FileSearchResult]:
        """Match file keys by glob pattern."""
        self._check("glob")
        prefix = self._scope.get("prefix")
        keys = self.repo.glob_files(pattern, prefix=prefix, limit=limit)
        return [FileSearchResult(id="", key=k) for k in keys]

    def tree(
        self,
        prefix: str | None = None,
        depth: int = 3,
    ) -> str:
        """Compact directory tree of file keys."""
        self._check("tree")
        effective_prefix = (
            self._full_key(prefix) if prefix else self._scope.get("prefix")
        )

        store = FileStore(self.repo)
        files = store.list_files(prefix=effective_prefix, limit=500)

        # Build tree structure
        tree_dict: dict = {}
        strip = (
            len(effective_prefix.rstrip("/") + "/") if effective_prefix else 0
        )
        for f in files:
            rel = f.key[strip:]
            parts = rel.split("/")
            node = tree_dict
            for p in parts[:depth]:
                node = node.setdefault(p, {})

        # Render
        lines: list[str] = []
        root_label = (
            effective_prefix.rstrip("/") + "/" if effective_prefix else "/"
        )
        lines.append(root_label)

        def _render(node: dict, indent: str) -> None:
            items = sorted(node.items())
            for i, (name, children) in enumerate(items):
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "
                suffix = "/" if children else ""
                lines.append(f"{indent}{connector}{name}{suffix}")
                if children:
                    extension = "    " if is_last else "│   "
                    _render(children, indent + extension)

        _render(tree_dict, "")
        return "\n".join(lines)

    def __repr__(self) -> str:
        prefix = self._scope.get("prefix", "")
        ro = " read-only" if self._scope.get("read_only") else ""
        if prefix:
            return f"<Dir '{prefix}'{ro} list() get(key) grep(pattern) glob(pattern) tree()>"
        return f"<DirCapability{ro} list() get(key) grep(pattern) glob(pattern) tree()>"

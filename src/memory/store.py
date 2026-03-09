"""MemoryStore: high-level versioned memory operations."""

from __future__ import annotations

import logging

from brain.db.models import Memory, MemoryVersion
from memory.errors import MemoryReadOnlyError

logger = logging.getLogger(__name__)


class MemoryStore:
    """Wraps a repository with versioned memory operations."""

    def __init__(self, repo) -> None:  # noqa: ANN001
        self._repo = repo

    # ───────────────────────────────────────────────────────────
    # Create / Version / Upsert
    # ───────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> Memory:
        """Create a new memory with version 1."""
        mem = Memory(name=name, active_version=1)
        mv = MemoryVersion(
            memory_id=mem.id,
            version=1,
            content=content,
            source=source,
            read_only=read_only,
        )
        mem.versions[1] = mv
        self._repo.insert_memory(mem)
        return mem

    def new_version(
        self,
        name: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> MemoryVersion | None:
        """Add a new version if content changed. Returns None if unchanged or not found.

        Does NOT check read_only on the current active version -- it creates a NEW version.
        """
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            return None

        # Check if content is unchanged vs active version
        active_mv = mem.versions.get(mem.active_version)
        if active_mv and active_mv.content == content:
            return None

        next_ver = self._repo.get_max_version(mem.id) + 1
        mv = MemoryVersion(
            memory_id=mem.id,
            version=next_ver,
            content=content,
            source=source,
            read_only=read_only,
        )
        self._repo.insert_memory_version(mv)
        self._repo.update_active_version(mem.id, next_ver)
        return mv

    def upsert(
        self,
        name: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> Memory | MemoryVersion | None:
        """Create or update a memory.

        - Creates if not exists (returns Memory).
        - Raises MemoryReadOnlyError if active version is read_only.
        - Returns None if content unchanged.
        - Otherwise creates new version (returns MemoryVersion).
        """
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            return self.create(name, content, source=source, read_only=read_only)

        active_mv = mem.versions.get(mem.active_version)
        if active_mv and active_mv.read_only:
            raise MemoryReadOnlyError(name, mem.active_version, active_mv.source)

        return self.new_version(name, content, source=source, read_only=read_only)

    # ───────────────────────────────────────────────────────────
    # Read
    # ───────────────────────────────────────────────────────────

    def get(self, name: str) -> Memory | None:
        """Get a memory by name."""
        return self._repo.get_memory_by_name(name)

    def get_by_id(self, memory_id) -> Memory | None:
        """Get a memory by ID."""
        return self._repo.get_memory_by_id(memory_id)

    def get_version(self, name: str, version: int) -> MemoryVersion | None:
        """Get a specific version of a memory."""
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            return None
        return self._repo.get_memory_version(mem.id, version)

    def list_memories(
        self,
        *,
        prefix: str | None = None,
        source: str | None = None,
        limit: int = 200,
    ) -> list[Memory]:
        """List memories with optional filters."""
        return self._repo.list_memories(prefix=prefix, source=source, limit=limit)

    def history(self, name: str) -> list[MemoryVersion]:
        """Return all versions for a memory."""
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            return []
        return self._repo.list_memory_versions(mem.id)

    # ───────────────────────────────────────────────────────────
    # Manage
    # ───────────────────────────────────────────────────────────

    def activate(self, name: str, version: int) -> None:
        """Switch the active version. Raises ValueError if version doesn't exist."""
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            raise ValueError(f"memory '{name}' not found")
        mv = self._repo.get_memory_version(mem.id, version)
        if mv is None:
            raise ValueError(
                f"version {version} does not exist for memory '{name}'"
            )
        self._repo.update_active_version(mem.id, version)

    def set_read_only(
        self, name: str, read_only: bool, *, version: int | None = None
    ) -> None:
        """Set read_only flag on a version (defaults to active version)."""
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            raise ValueError(f"memory '{name}' not found")
        ver = version if version is not None else mem.active_version
        self._repo.update_version_read_only(mem.id, ver, read_only)

    def rename(self, old_name: str, new_name: str) -> None:
        """Rename a memory. Raises ValueError if not found."""
        mem = self._repo.get_memory_by_name(old_name)
        if mem is None:
            raise ValueError(f"memory '{old_name}' not found")
        self._repo.update_memory_name(mem.id, new_name)

    # ───────────────────────────────────────────────────────────
    # Delete
    # ───────────────────────────────────────────────────────────

    def delete(self, name: str, *, version: int | None = None) -> None:
        """Delete a memory or a specific version.

        Without version: deletes entire memory. Raises MemoryReadOnlyError if active is read_only.
        With version: deletes single version. Raises ValueError if it's the active version.
        """
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            raise ValueError(f"memory '{name}' not found")

        if version is None:
            active_mv = mem.versions.get(mem.active_version)
            if active_mv and active_mv.read_only:
                raise MemoryReadOnlyError(
                    name, mem.active_version, active_mv.source
                )
            self._repo.delete_memory(mem.id)
        else:
            if version == mem.active_version:
                raise ValueError(
                    f"cannot delete active version {version} of memory '{name}'"
                )
            self._repo.delete_memory_version(mem.id, version)

    # ───────────────────────────────────────────────────────────
    # Includes Resolution
    # ───────────────────────────────────────────────────────────

    def resolve_includes(self, name: str) -> list[Memory]:
        """Recursively resolve a memory's includes, with cycle detection.

        Returns all included memories (not the root memory itself).
        """
        mem = self._repo.get_memory_by_name(name)
        if not mem or not mem.includes:
            return []
        visited: set[str] = {name}
        result: list[Memory] = []
        self._resolve_includes_rec(mem.includes, visited, result)
        return result

    def _resolve_includes_rec(
        self, keys: list[str], visited: set[str], result: list[Memory],
    ) -> None:
        resolved = self._repo.resolve_memory_keys(keys)
        for mem in resolved:
            if mem.name in visited:
                continue
            visited.add(mem.name)
            result.append(mem)
            if mem.includes:
                self._resolve_includes_rec(mem.includes, visited, result)

    def resolve_keys(self, keys: list[str]) -> list[Memory]:
        """Resolve memory keys — delegates to repo."""
        return self._repo.resolve_memory_keys(keys)

    def update_includes(self, name: str, includes: list[str]) -> None:
        """Update the includes list on a memory."""
        mem = self._repo.get_memory_by_name(name)
        if mem is None:
            raise ValueError(f"memory '{name}' not found")
        self._repo.update_memory_includes(mem.id, includes)

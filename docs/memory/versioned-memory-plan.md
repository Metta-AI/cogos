# Versioned Memory System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat memory system with versioned memories supporting active-version pointers, read-only flags, and source tracking.

**Architecture:** Two-table model (`memory` + `memory_version`). `memory` holds identity + active_version pointer. `memory_version` holds content per version. Store-level enforcement for read-only. Version bumps only on content change.

**Tech Stack:** Python, Pydantic, PostgreSQL (RDS Data API), Click CLI, pytest

**Design doc:** `docs/memory/versioned-memory-design.md`

---

## Task 1: New Pydantic Models

**Files:**
- Modify: `src/brain/db/models.py`
- Create: `tests/memory/test_models.py`

**Step 1: Write tests for new models**

Create `tests/memory/test_models.py`:

```python
"""Tests for Memory and MemoryVersion models."""
from brain.db.models import Memory, MemoryVersion


class TestMemoryVersion:
    def test_defaults(self):
        mv = MemoryVersion(memory_id="00000000-0000-0000-0000-000000000001", version=1)
        assert mv.version == 1
        assert mv.read_only is False
        assert mv.content == ""
        assert mv.source == "cogent"

    def test_source_values(self):
        for source in ["polis", "cogent", "user:daveey"]:
            mv = MemoryVersion(
                memory_id="00000000-0000-0000-0000-000000000001",
                version=1,
                source=source,
            )
            assert mv.source == source


class TestMemory:
    def test_defaults(self):
        m = Memory(name="/test")
        assert m.active_version == 1
        assert m.versions == {}

    def test_with_versions(self):
        m = Memory(name="/test", active_version=2)
        mv = MemoryVersion(memory_id=m.id, version=1, content="v1")
        m.versions[1] = mv
        assert m.versions[1].content == "v1"
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/memory/test_models.py -v
```

Expected: ImportError — `Memory` and `MemoryVersion` don't exist yet.

**Step 3: Add new models to models.py**

In `src/brain/db/models.py`, add after the existing `MemoryRecord` class (don't remove it yet — other code still references it):

```python
class MemoryVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_id: UUID
    version: int
    read_only: bool = False
    content: str = ""
    source: str = "cogent"
    created_at: datetime | None = None


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    active_version: int = 1
    versions: dict[int, MemoryVersion] = Field(default_factory=dict)
    created_at: datetime | None = None
    modified_at: datetime | None = None
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/memory/test_models.py -v
```

**Step 5: Commit**

```bash
git add src/brain/db/models.py tests/memory/test_models.py && git commit -m "feat(memory): add Memory and MemoryVersion models"
```

---

## Task 2: MemoryReadOnlyError

**Files:**
- Create: `src/memory/errors.py`

**Step 1: Create error module**

```python
"""Memory system errors."""


class MemoryReadOnlyError(Exception):
    """Raised when attempting to mutate a read-only memory version."""

    def __init__(self, name: str, version: int, source: str) -> None:
        self.name = name
        self.version = version
        self.source = source
        super().__init__(
            f"memory '{name}' version {version} is read-only (source={source})"
        )
```

**Step 2: Commit**

```bash
git add src/memory/errors.py && git commit -m "feat(memory): add MemoryReadOnlyError"
```

---

## Task 3: Rewrite MemoryStore with Versioning

**Files:**
- Modify: `src/memory/store.py`
- Modify: `tests/memory/test_store.py`

This is the core task. The store needs new methods and the existing ones need to change.

**Step 1: Write failing tests for the new store**

Replace `tests/memory/test_store.py` entirely. The new store uses a `LocalRepository` (which we'll update in Task 4), so for now we mock the repo interface. Key test classes:

```python
"""Tests for memory.store.MemoryStore — versioned memory."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from brain.db.models import Memory, MemoryVersion
from memory.errors import MemoryReadOnlyError
from memory.store import MemoryStore


@pytest.fixture
def repo():
    """Mock repository with versioned memory methods."""
    r = MagicMock()
    r.get_memory_by_name.return_value = None
    r.list_memory_versions.return_value = []
    return r


@pytest.fixture
def store(repo):
    return MemoryStore(repo)


def _memory(name: str, version: int = 1, content: str = "hello", source: str = "cogent", read_only: bool = False) -> Memory:
    mid = uuid4()
    mv = MemoryVersion(memory_id=mid, version=version, content=content, source=source, read_only=read_only)
    return Memory(id=mid, name=name, active_version=version, versions={version: mv})


class TestCreate:
    def test_creates_new_memory_with_version_1(self, store, repo):
        repo.get_memory_by_name.return_value = None
        store.create("/test", "content", source="cogent")
        repo.insert_memory.assert_called_once()
        repo.insert_memory_version.assert_called_once()
        mv = repo.insert_memory_version.call_args[0][0]
        assert mv.version == 1
        assert mv.content == "content"
        assert mv.source == "cogent"


class TestNewVersion:
    def test_adds_version_when_content_changed(self, store, repo):
        existing = _memory("/test", version=1, content="old")
        repo.get_memory_by_name.return_value = existing
        repo.get_max_version.return_value = 1

        store.new_version("/test", "new content", source="polis")

        repo.insert_memory_version.assert_called_once()
        mv = repo.insert_memory_version.call_args[0][0]
        assert mv.version == 2
        assert mv.content == "new content"
        repo.update_active_version.assert_called_once_with(existing.id, 2)

    def test_skips_when_content_unchanged(self, store, repo):
        existing = _memory("/test", version=1, content="same")
        repo.get_memory_by_name.return_value = existing

        result = store.new_version("/test", "same", source="polis")

        repo.insert_memory_version.assert_not_called()
        assert result is None

    def test_read_only_does_not_block_new_version(self, store, repo):
        """New version creates a new row; read_only on old version is irrelevant."""
        existing = _memory("/test", version=1, content="old", read_only=True)
        repo.get_memory_by_name.return_value = existing
        repo.get_max_version.return_value = 1

        store.new_version("/test", "new content", source="polis")

        repo.insert_memory_version.assert_called_once()


class TestUpsert:
    def test_creates_when_not_exists(self, store, repo):
        repo.get_memory_by_name.return_value = None
        store.upsert("/test", "content", source="cogent")
        repo.insert_memory.assert_called_once()

    def test_raises_when_active_version_read_only(self, store, repo):
        existing = _memory("/test", version=1, content="old", read_only=True, source="polis")
        repo.get_memory_by_name.return_value = existing

        with pytest.raises(MemoryReadOnlyError, match="read-only"):
            store.upsert("/test", "new content", source="user:daveey")

    def test_skips_when_content_unchanged(self, store, repo):
        existing = _memory("/test", version=1, content="same")
        repo.get_memory_by_name.return_value = existing

        result = store.upsert("/test", "same", source="cogent")

        repo.insert_memory_version.assert_not_called()


class TestActivate:
    def test_switches_active_version(self, store, repo):
        mid = uuid4()
        repo.get_memory_by_name.return_value = Memory(id=mid, name="/test", active_version=1)
        repo.get_memory_version.return_value = MemoryVersion(memory_id=mid, version=2, content="v2")

        store.activate("/test", 2)

        repo.update_active_version.assert_called_once_with(mid, 2)

    def test_raises_when_version_not_found(self, store, repo):
        mid = uuid4()
        repo.get_memory_by_name.return_value = Memory(id=mid, name="/test", active_version=1)
        repo.get_memory_version.return_value = None

        with pytest.raises(ValueError, match="version 99"):
            store.activate("/test", 99)


class TestSetReadOnly:
    def test_sets_read_only(self, store, repo):
        mid = uuid4()
        existing = _memory("/test", version=1)
        repo.get_memory_by_name.return_value = existing

        store.set_read_only("/test", True)

        repo.update_version_read_only.assert_called_once_with(mid, 1, True)

    def test_sets_specific_version(self, store, repo):
        mid = uuid4()
        existing = _memory("/test", version=1)
        repo.get_memory_by_name.return_value = existing
        repo.get_memory_version.return_value = MemoryVersion(memory_id=mid, version=3, content="v3")

        store.set_read_only("/test", True, version=3)

        repo.update_version_read_only.assert_called_once_with(mid, 3, True)


class TestResolveKeys:
    """resolve_keys should work as before but fetch active version content."""

    def test_returns_active_version_content(self, store, repo):
        mid = uuid4()
        mv = MemoryVersion(memory_id=mid, version=2, content="active content")
        mem = Memory(id=mid, name="/test", active_version=2, versions={2: mv})
        repo.resolve_memory_keys.return_value = [mem]

        result = store.resolve_keys(["/test"])

        assert len(result) == 1
        assert result[0].versions[result[0].active_version].content == "active content"


class TestDelete:
    def test_delete_entire_memory(self, store, repo):
        existing = _memory("/test", version=1, read_only=False)
        repo.get_memory_by_name.return_value = existing

        store.delete("/test")

        repo.delete_memory.assert_called_once_with(existing.id)

    def test_delete_raises_when_active_version_read_only(self, store, repo):
        existing = _memory("/test", version=1, read_only=True, source="polis")
        repo.get_memory_by_name.return_value = existing

        with pytest.raises(MemoryReadOnlyError):
            store.delete("/test")

    def test_delete_specific_version(self, store, repo):
        existing = _memory("/test", version=1)
        repo.get_memory_by_name.return_value = existing

        store.delete("/test", version=2)

        repo.delete_memory_version.assert_called_once_with(existing.id, 2)

    def test_delete_active_version_raises(self, store, repo):
        existing = _memory("/test", version=1)
        repo.get_memory_by_name.return_value = existing

        with pytest.raises(ValueError, match="active version"):
            store.delete("/test", version=1)


class TestRename:
    def test_renames_memory(self, store, repo):
        existing = _memory("/old", version=1)
        repo.get_memory_by_name.return_value = existing

        store.rename("/old", "/new")

        repo.update_memory_name.assert_called_once_with(existing.id, "/new")

    def test_rename_not_found_raises(self, store, repo):
        repo.get_memory_by_name.return_value = None

        with pytest.raises(ValueError, match="not found"):
            store.rename("/old", "/new")
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/memory/test_store.py -v
```

Expected: Failures because `MemoryStore` still has old API.

**Step 3: Rewrite MemoryStore**

Replace `src/memory/store.py`:

```python
"""MemoryStore: versioned memory operations with read-only enforcement."""
from __future__ import annotations

import logging

from brain.db.models import Memory, MemoryVersion
from memory.errors import MemoryReadOnlyError

logger = logging.getLogger(__name__)


class MemoryStore:
    """Versioned memory store with read-only enforcement and hierarchical key resolution."""

    def __init__(self, repo) -> None:
        self._repo = repo

    # ── Create / Version / Upsert ─────────────────────────────

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
        self._repo.insert_memory(mem)

        mv = MemoryVersion(
            memory_id=mem.id,
            version=1,
            content=content,
            source=source,
            read_only=read_only,
        )
        self._repo.insert_memory_version(mv)

        mem.versions[1] = mv
        return mem

    def new_version(
        self,
        name: str,
        content: str,
        *,
        source: str = "cogent",
        read_only: bool = False,
    ) -> MemoryVersion | None:
        """Add a new version if content changed. Returns None if unchanged."""
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            raise ValueError(f"memory '{name}' not found")

        active = mem.versions.get(mem.active_version)
        if active and active.content == content:
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
        """Create or update a memory. Raises MemoryReadOnlyError if active version is read-only."""
        existing = self._repo.get_memory_by_name(name)
        if not existing:
            return self.create(name, content, source=source, read_only=read_only)

        active = existing.versions.get(existing.active_version)
        if active and active.read_only:
            raise MemoryReadOnlyError(name, existing.active_version, active.source)

        return self.new_version(name, content, source=source, read_only=read_only)

    # ── Read ──────────────────────────────────────────────────

    def get(self, name: str) -> Memory | None:
        return self._repo.get_memory_by_name(name)

    def get_version(self, name: str, version: int) -> MemoryVersion | None:
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            return None
        return self._repo.get_memory_version(mem.id, version)

    def list_memories(
        self,
        *,
        prefix: str | None = None,
        source: str | None = None,
        limit: int = 200,
    ) -> list[Memory]:
        return self._repo.list_memories(prefix=prefix, source=source, limit=limit)

    def history(self, name: str) -> list[MemoryVersion]:
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            return []
        return self._repo.list_memory_versions(mem.id)

    # ── Manage ────────────────────────────────────────────────

    def activate(self, name: str, version: int) -> None:
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            raise ValueError(f"memory '{name}' not found")
        mv = self._repo.get_memory_version(mem.id, version)
        if not mv:
            raise ValueError(f"memory '{name}' has no version {version}")
        self._repo.update_active_version(mem.id, version)

    def set_read_only(self, name: str, read_only: bool, *, version: int | None = None) -> None:
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            raise ValueError(f"memory '{name}' not found")
        target_version = version or mem.active_version
        if version:
            mv = self._repo.get_memory_version(mem.id, version)
            if not mv:
                raise ValueError(f"memory '{name}' has no version {version}")
        self._repo.update_version_read_only(mem.id, target_version, read_only)

    def rename(self, old_name: str, new_name: str) -> None:
        mem = self._repo.get_memory_by_name(old_name)
        if not mem:
            raise ValueError(f"memory '{old_name}' not found")
        self._repo.update_memory_name(mem.id, new_name)

    # ── Delete ────────────────────────────────────────────────

    def delete(self, name: str, *, version: int | None = None) -> None:
        mem = self._repo.get_memory_by_name(name)
        if not mem:
            raise ValueError(f"memory '{name}' not found")

        if version is not None:
            if version == mem.active_version:
                raise ValueError(f"cannot delete active version {version} of '{name}'")
            self._repo.delete_memory_version(mem.id, version)
        else:
            active = mem.versions.get(mem.active_version)
            if active and active.read_only:
                raise MemoryReadOnlyError(name, mem.active_version, active.source)
            self._repo.delete_memory(mem.id)

    # ── Key Resolution ────────────────────────────────────────

    def resolve_keys(self, keys: list[str]) -> list[Memory]:
        """Resolve memory keys with ancestor/child init expansion.

        Returns Memory objects with their active version populated.
        COGENT-sourced records shadow POLIS-sourced with the same name.
        Results sorted root-to-leaf by path depth.
        """
        if not keys:
            return []
        return self._repo.resolve_memory_keys(keys)
```

**Step 4: Run tests to verify they pass**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/memory/test_store.py -v
```

**Step 5: Commit**

```bash
git add src/memory/store.py src/memory/errors.py tests/memory/test_store.py && git commit -m "feat(memory): rewrite MemoryStore with versioning and read-only enforcement"
```

---

## Task 4: LocalRepository — Versioned Memory Methods

**Files:**
- Modify: `src/brain/db/local_repository.py`
- Create: `tests/brain/test_local_repo_memory.py`

**Step 1: Write failing tests**

Create `tests/brain/test_local_repo_memory.py`:

```python
"""Tests for LocalRepository versioned memory methods."""
from __future__ import annotations

import tempfile

import pytest

from brain.db.local_repository import LocalRepository
from brain.db.models import Memory, MemoryVersion


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(data_dir=str(tmp_path))


class TestInsertAndGetMemory:
    def test_insert_and_get_by_name(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        result = repo.get_memory_by_name("/test")
        assert result is not None
        assert result.name == "/test"

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get_memory_by_name("/nope") is None


class TestMemoryVersions:
    def test_insert_and_get_version(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        mv = MemoryVersion(memory_id=mem.id, version=1, content="v1", source="cogent")
        repo.insert_memory_version(mv)

        result = repo.get_memory_version(mem.id, 1)
        assert result is not None
        assert result.content == "v1"

    def test_get_max_version(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="v1"))
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=2, content="v2"))
        assert repo.get_max_version(mem.id) == 2

    def test_get_max_version_no_versions(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        assert repo.get_max_version(mem.id) == 0

    def test_list_memory_versions(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="v1"))
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=2, content="v2"))

        versions = repo.list_memory_versions(mem.id)
        assert len(versions) == 2
        assert versions[0].version == 1
        assert versions[1].version == 2


class TestUpdateActiveVersion:
    def test_updates_active_version(self, repo):
        mem = Memory(name="/test", active_version=1)
        repo.insert_memory(mem)
        repo.update_active_version(mem.id, 2)
        result = repo.get_memory_by_name("/test")
        assert result.active_version == 2


class TestUpdateReadOnly:
    def test_sets_read_only(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="v1"))
        repo.update_version_read_only(mem.id, 1, True)

        result = repo.get_memory_version(mem.id, 1)
        assert result.read_only is True


class TestUpdateMemoryName:
    def test_renames(self, repo):
        mem = Memory(name="/old")
        repo.insert_memory(mem)
        repo.update_memory_name(mem.id, "/new")
        assert repo.get_memory_by_name("/old") is None
        assert repo.get_memory_by_name("/new") is not None


class TestDeleteMemory:
    def test_deletes_memory_and_versions(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="v1"))
        repo.delete_memory(mem.id)

        assert repo.get_memory_by_name("/test") is None

    def test_delete_single_version(self, repo):
        mem = Memory(name="/test")
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="v1"))
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=2, content="v2"))
        repo.delete_memory_version(mem.id, 1)

        assert repo.get_memory_version(mem.id, 1) is None
        assert repo.get_memory_version(mem.id, 2) is not None


class TestListMemories:
    def test_list_with_prefix(self, repo):
        repo.insert_memory(Memory(name="/mind/a"))
        repo.insert_memory(Memory(name="/mind/b"))
        repo.insert_memory(Memory(name="/other"))

        result = repo.list_memories(prefix="/mind")
        assert len(result) == 2

    def test_list_with_source_filter(self, repo):
        m1 = Memory(name="/a")
        m2 = Memory(name="/b")
        repo.insert_memory(m1)
        repo.insert_memory(m2)
        repo.insert_memory_version(MemoryVersion(memory_id=m1.id, version=1, source="polis", content="x"))
        repo.insert_memory_version(MemoryVersion(memory_id=m2.id, version=1, source="cogent", content="y"))
        m1.active_version = 1
        m2.active_version = 1
        repo.update_active_version(m1.id, 1)
        repo.update_active_version(m2.id, 1)

        result = repo.list_memories(source="polis")
        names = [m.name for m in result]
        assert "/a" in names
        assert "/b" not in names


class TestGetMemoryByNameWithVersions:
    def test_returns_memory_with_active_version_populated(self, repo):
        mem = Memory(name="/test", active_version=1)
        repo.insert_memory(mem)
        repo.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="hello"))

        result = repo.get_memory_by_name("/test")
        assert result.active_version == 1
        assert result.versions[1].content == "hello"


class TestPersistence:
    def test_data_survives_reload(self, tmp_path):
        repo1 = LocalRepository(data_dir=str(tmp_path))
        mem = Memory(name="/persist")
        repo1.insert_memory(mem)
        repo1.insert_memory_version(MemoryVersion(memory_id=mem.id, version=1, content="saved"))

        repo2 = LocalRepository(data_dir=str(tmp_path))
        result = repo2.get_memory_by_name("/persist")
        assert result is not None
        assert result.versions[1].content == "saved"
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/brain/test_local_repo_memory.py -v
```

**Step 3: Implement versioned memory methods in LocalRepository**

In `src/brain/db/local_repository.py`, replace the Memory section (`# ── Memory ──`) with new versioned methods. Also update `_load` and `_save` for the new data shape.

Key changes:
- Replace `self._memory: dict[UUID, MemoryRecord]` with `self._memories: dict[UUID, Memory]` and `self._memory_versions: dict[UUID, list[MemoryVersion]]` (keyed by memory_id)
- Update `_load()` to deserialize from new JSON shape: `{"memories": [...], "memory_versions": [...]}`
- Update `_save()` to serialize both
- Add methods: `insert_memory(Memory)`, `get_memory_by_name(str)`, `insert_memory_version(MemoryVersion)`, `get_memory_version(UUID, int)`, `get_max_version(UUID)`, `list_memory_versions(UUID)`, `update_active_version(UUID, int)`, `update_version_read_only(UUID, int, bool)`, `update_memory_name(UUID, str)`, `delete_memory(UUID)`, `delete_memory_version(UUID, int)`, `list_memories(prefix, source, limit)`, `resolve_memory_keys(list[str])`
- `get_memory_by_name` should populate `memory.versions` dict with all versions for that memory (at minimum the active version)
- `resolve_memory_keys` should implement the same ancestor/child init expansion logic currently in `MemoryStore.resolve_keys`, but returning `Memory` objects

**Step 4: Run tests to verify they pass**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/brain/test_local_repo_memory.py -v
```

**Step 5: Commit**

```bash
git add src/brain/db/local_repository.py tests/brain/test_local_repo_memory.py && git commit -m "feat(memory): add versioned memory methods to LocalRepository"
```

---

## Task 5: RDS Repository — Versioned Memory Methods

**Files:**
- Modify: `src/brain/db/repository.py`
- Modify: `src/brain/db/migrations.py`

**Step 1: Add DB migration for new tables**

In `src/brain/db/migrations.py`, add a new migration step that:
1. Creates `memory_new` table (renamed later) and `memory_version` table per the schema in the design doc
2. Migrates existing data: for each row in old `memory` table, creates a `memory_new` row and a `memory_version` row (version=1, source from old scope, read_only=true if scope was polis)
3. Drops old `memory` table, renames `memory_new` to `memory`

**Step 2: Rewrite memory methods in Repository**

Replace the `# MEMORY` section in `src/brain/db/repository.py` with methods matching the interface defined in Task 4's LocalRepository:
- `insert_memory(Memory)` → INSERT into `memory` table
- `get_memory_by_name(str)` → SELECT from `memory` JOIN `memory_version` WHERE name = :name
- `insert_memory_version(MemoryVersion)` → INSERT into `memory_version`
- `get_memory_version(UUID, int)` → SELECT from `memory_version` WHERE memory_id = :id AND version = :ver
- `get_max_version(UUID)` → SELECT MAX(version) FROM memory_version WHERE memory_id = :id
- `list_memory_versions(UUID)` → SELECT from `memory_version` WHERE memory_id = :id ORDER BY version
- `update_active_version(UUID, int)` → UPDATE memory SET active_version = :ver WHERE id = :id
- `update_version_read_only(UUID, int, bool)` → UPDATE memory_version SET read_only = :ro WHERE memory_id = :id AND version = :ver
- `update_memory_name(UUID, str)` → UPDATE memory SET name = :name WHERE id = :id
- `delete_memory(UUID)` → DELETE from `memory_version` WHERE memory_id = :id; DELETE FROM memory WHERE id = :id
- `delete_memory_version(UUID, int)` → DELETE from `memory_version` WHERE memory_id = :id AND version = :ver
- `list_memories(prefix, source, limit)` → SELECT with optional filters, JOIN to get active version source
- `resolve_memory_keys(list[str])` → Implement ancestor/child init expansion with JOIN

Also remove old methods: `query_memory`, `query_memory_by_prefixes`, `get_memories_by_names`, `delete_memories_by_prefix`.

**Step 3: Commit**

```bash
git add src/brain/db/repository.py src/brain/db/migrations.py && git commit -m "feat(memory): add versioned memory tables and repository methods"
```

---

## Task 6: Update ContextEngine

**Files:**
- Modify: `src/memory/context_engine.py`

**Step 1: Update resolve_keys usage**

The `ContextEngine.build_system_prompt` method calls `self._memory.resolve_keys(program.memory_keys)` and iterates over results expecting `.name` and `.content`. Now results are `Memory` objects. Update the memory layer section:

```python
# Layer 80: Declared memories
if program.memory_keys:
    memories = self._memory.resolve_keys(program.memory_keys)
    if memories:
        sections = []
        for mem in memories:
            label = mem.name or "unnamed"
            active = mem.versions.get(mem.active_version)
            content = active.content if active else ""
            sections.append(f"<memory name=\"{label}\">\n{content}\n</memory>")
        memory_text = "\n\n".join(sections)
        layers.append(ContextLayer(
            name="memory",
            content=memory_text,
            priority=80,
            max_tokens=30_000,
        ))
```

**Step 2: Commit**

```bash
git add src/memory/context_engine.py && git commit -m "refactor(memory): update ContextEngine for versioned Memory objects"
```

---

## Task 7: Update mind update Polis Sync

**Files:**
- Modify: `src/mind/cli.py` (the hatch/update command, around line 270-285)
- Modify: `src/mind/memory_loader.py`
- Modify: `src/mind/bootstrap_loader.py`

**Step 1: Update memory_loader to return source="polis"**

In `src/mind/memory_loader.py`, the `_mem_from_dict` function currently creates `MemoryRecord` objects. Change it to return a simple dict or namedtuple with `name`, `content`, `source`. Since this is a loader (not persisted), a simple dataclass or dict is fine:

```python
from dataclasses import dataclass

@dataclass
class LoadedMemory:
    name: str
    content: str
    source: str = "polis"
```

Update `_load_markdown` and `_load_yaml` to return `LoadedMemory` objects. The `scope` frontmatter field maps to `source`.

**Step 2: Update mind update sync logic**

In `src/mind/cli.py`, replace the memories sync section (~line 270-285) with the polis sync logic from the design doc:

```python
# 4. Memories
memories_dir = egg / "memories"
if memories_dir.is_dir():
    from memory.store import MemoryStore
    mem_store = MemoryStore(repo)

    loaded = load_memories_from_dir(memories_dir)
    created = updated = skipped = unchanged = 0
    for lm in loaded:
        existing = mem_store.get(lm.name)
        if not existing:
            mem_store.create(lm.name, lm.content, source="polis", read_only=True)
            created += 1
        else:
            active = existing.versions.get(existing.active_version)
            if active and active.source.startswith("user:"):
                skipped += 1
            elif active and active.content == lm.content:
                unchanged += 1
            else:
                mem_store.new_version(lm.name, lm.content, source="polis", read_only=True)
                updated += 1
    click.echo(f"Memories: {created} created, {updated} updated, {skipped} skipped (user override), {unchanged} unchanged")
```

**Step 3: Update bootstrap_loader**

In `src/mind/bootstrap_loader.py`, update the memory section to use the new store API instead of directly calling `repo.insert_memory(MemoryRecord(...))`. Bootstrap memories should use `source="cogent"`.

**Step 4: Commit**

```bash
git add src/mind/cli.py src/mind/memory_loader.py src/mind/bootstrap_loader.py && git commit -m "feat(memory): update mind update for versioned polis sync"
```

---

## Task 8: Rewrite Memory CLI

**Files:**
- Modify: `src/memory/cli.py`

**Step 1: Rewrite CLI commands**

Replace `src/memory/cli.py` with the new command set. Each command uses `MemoryStore` (not repo directly). Commands:

- `memory status` — counts by source, read_only stats
- `memory list` — shows name, active_version, source, read_only, content preview
- `memory get <name> [--version N]` — shows full content
- `memory history <name>` — lists all versions
- `memory put <path> [--prefix] [--source] [--force]` — upsert from .md files
- `memory activate <name> <version>` — switch active version
- `memory set-ro <name> [--version N] [--off]` — toggle read-only
- `memory rename <old> <new>` — rename
- `memory delete <name> [--version N] [--yes]` — delete

For `put --force`: bypass read_only by calling `store.new_version()` directly (which doesn't check read_only on old versions) instead of `store.upsert()`.

**Step 2: Commit**

```bash
git add src/memory/cli.py && git commit -m "feat(memory): rewrite CLI with versioning commands"
```

---

## Task 9: Update Dashboard Router

**Files:**
- Modify: `src/dashboard/routers/memory.py`

**Step 1: Update API endpoints**

Update the memory router to use `Memory` and `MemoryVersion` models instead of `MemoryRecord`. Key changes:
- `list_memory` returns Memory objects with active version info
- `create_memory` uses `MemoryStore.create()`
- `update_memory` uses `MemoryStore.new_version()` or `MemoryStore.upsert()`
- `delete_memory` uses `MemoryStore.delete()`
- Add version-specific endpoints if needed

**Step 2: Commit**

```bash
git add src/dashboard/routers/memory.py && git commit -m "refactor(memory): update dashboard router for versioned memory"
```

---

## Task 10: Clean Up Old Models and Imports

**Files:**
- Modify: `src/brain/db/models.py` — remove `MemoryRecord`, `MemoryScope`
- Modify: `src/brain/db/__init__.py` — update exports
- Modify: `src/brain/db/local_repository.py` — remove old `MemoryRecord`/`MemoryScope` imports
- Modify: any remaining files importing old types

**Step 1: Remove MemoryRecord and MemoryScope from models.py**

**Step 2: Fix all remaining imports**

Search for `MemoryRecord` and `MemoryScope` across the codebase and update/remove all references.

```bash
cd /Users/daveey/code/cogents/cogents.4 && grep -r "MemoryRecord\|MemoryScope" src/ --include="*.py" -l
```

Fix each file.

**Step 3: Run full test suite**

```bash
cd /Users/daveey/code/cogents/cogents.4 && python -m pytest tests/ -v
```

**Step 4: Commit**

```bash
git add -u && git commit -m "refactor(memory): remove MemoryRecord and MemoryScope"
```

---

## Task 11: Update __init__.py Exports

**Files:**
- Modify: `src/memory/__init__.py`

Update exports:

```python
"""Versioned memory store and context engine."""
from memory.context_engine import ContextEngine
from memory.errors import MemoryReadOnlyError
from memory.store import MemoryStore

__all__ = ["ContextEngine", "MemoryReadOnlyError", "MemoryStore"]
```

**Step 1: Commit**

```bash
git add src/memory/__init__.py && git commit -m "refactor(memory): update package exports"
```

---

## Dependency Order

```
Task 1 (models) ──┐
Task 2 (errors) ──┤
                   ├── Task 3 (store) ──┐
                   │                     ├── Task 6 (context engine)
Task 4 (local repo)┘                    ├── Task 7 (mind update)
                                         ├── Task 8 (CLI)
Task 5 (RDS repo) ──────────────────────├── Task 9 (dashboard)
                                         └── Task 10 (cleanup) ── Task 11 (exports)
```

Tasks 1, 2, 4, 5 can be parallelized.
Tasks 6, 7, 8, 9 can be parallelized after Task 3.
Task 10 must come last (after all callers are updated).

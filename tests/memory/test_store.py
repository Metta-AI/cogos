"""Tests for memory.store.MemoryStore (versioned memory system)."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from brain.db.models import Memory, MemoryVersion
from memory.errors import MemoryReadOnlyError
from memory.store import MemoryStore


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def store(repo):
    return MemoryStore(repo)


def _memory(
    name: str,
    content: str = "hello",
    *,
    version: int = 1,
    read_only: bool = False,
    source: str = "cogent",
) -> Memory:
    """Helper to build a Memory with its active version populated."""
    mid = uuid4()
    mv = MemoryVersion(
        memory_id=mid,
        version=version,
        read_only=read_only,
        content=content,
        source=source,
    )
    return Memory(
        id=mid,
        name=name,
        active_version=version,
        versions={version: mv},
    )


# ── TestCreate ──


class TestCreate:
    def test_creates_memory_with_version_1(self, store, repo):
        repo.get_memory_by_name.return_value = None
        repo.insert_memory_v2.return_value = uuid4()

        result = store.create("notes", "my content")

        assert isinstance(result, Memory)
        assert result.name == "notes"
        assert result.active_version == 1
        assert 1 in result.versions
        assert result.versions[1].content == "my content"
        assert result.versions[1].version == 1
        assert result.versions[1].source == "cogent"
        assert result.versions[1].read_only is False

    def test_create_with_read_only(self, store, repo):
        repo.get_memory_by_name.return_value = None
        repo.insert_memory_v2.return_value = uuid4()

        result = store.create("notes", "content", read_only=True)

        assert result.versions[1].read_only is True

    def test_create_with_custom_source(self, store, repo):
        repo.get_memory_by_name.return_value = None
        repo.insert_memory_v2.return_value = uuid4()

        result = store.create("notes", "content", source="polis")

        assert result.versions[1].source == "polis"

    def test_create_calls_repo_insert(self, store, repo):
        repo.get_memory_by_name.return_value = None
        repo.insert_memory_v2.return_value = uuid4()

        store.create("notes", "content")

        repo.insert_memory_v2.assert_called_once()
        mem = repo.insert_memory_v2.call_args[0][0]
        assert isinstance(mem, Memory)
        assert mem.name == "notes"


# ── TestNewVersion ──


class TestNewVersion:
    def test_adds_version_when_content_changed(self, store, repo):
        existing = _memory("notes", "old content", version=1)
        repo.get_memory_by_name.return_value = existing
        repo.get_max_version.return_value = 1

        result = store.new_version("notes", "new content")

        assert isinstance(result, MemoryVersion)
        assert result.version == 2
        assert result.content == "new content"
        repo.insert_memory_version.assert_called_once()
        repo.update_active_version.assert_called_once_with(existing.id, 2)

    def test_returns_none_when_content_unchanged(self, store, repo):
        existing = _memory("notes", "same content", version=1)
        repo.get_memory_by_name.return_value = existing

        result = store.new_version("notes", "same content")

        assert result is None
        repo.insert_memory_version.assert_not_called()

    def test_read_only_on_old_version_does_not_block(self, store, repo):
        existing = _memory("notes", "old", version=1, read_only=True)
        repo.get_memory_by_name.return_value = existing
        repo.get_max_version.return_value = 1

        result = store.new_version("notes", "new content")

        assert isinstance(result, MemoryVersion)
        assert result.version == 2

    def test_returns_none_when_memory_not_found(self, store, repo):
        repo.get_memory_by_name.return_value = None

        result = store.new_version("nonexistent", "content")

        assert result is None


# ── TestUpsert ──


class TestUpsert:
    def test_creates_when_not_exists(self, store, repo):
        repo.get_memory_by_name.return_value = None
        repo.insert_memory_v2.return_value = uuid4()

        result = store.upsert("notes", "content")

        assert isinstance(result, Memory)
        repo.insert_memory_v2.assert_called_once()

    def test_raises_when_active_is_read_only(self, store, repo):
        existing = _memory("notes", "locked", version=1, read_only=True)
        repo.get_memory_by_name.return_value = existing

        with pytest.raises(MemoryReadOnlyError) as exc_info:
            store.upsert("notes", "new content")

        assert exc_info.value.name == "notes"
        assert exc_info.value.version == 1

    def test_skips_when_content_unchanged(self, store, repo):
        existing = _memory("notes", "same", version=1)
        repo.get_memory_by_name.return_value = existing

        result = store.upsert("notes", "same")

        assert result is None
        repo.insert_memory_version.assert_not_called()

    def test_creates_new_version_when_content_changed(self, store, repo):
        existing = _memory("notes", "old", version=1)
        repo.get_memory_by_name.return_value = existing
        repo.get_max_version.return_value = 1

        result = store.upsert("notes", "new")

        assert isinstance(result, MemoryVersion)
        assert result.version == 2


# ── TestActivate ──


class TestActivate:
    def test_switches_active_version(self, store, repo):
        mem = _memory("notes", "v1", version=1)
        repo.get_memory_by_name.return_value = mem
        repo.get_memory_version.return_value = MemoryVersion(
            memory_id=mem.id, version=2, content="v2"
        )

        store.activate("notes", 2)

        repo.update_active_version.assert_called_once_with(mem.id, 2)

    def test_raises_when_version_not_found(self, store, repo):
        mem = _memory("notes", "v1", version=1)
        repo.get_memory_by_name.return_value = mem
        repo.get_memory_version.return_value = None

        with pytest.raises(ValueError):
            store.activate("notes", 99)


# ── TestSetReadOnly ──


class TestSetReadOnly:
    def test_sets_read_only_on_active_version(self, store, repo):
        mem = _memory("notes", "content", version=1)
        repo.get_memory_by_name.return_value = mem

        store.set_read_only("notes", True)

        repo.update_version_read_only.assert_called_once_with(mem.id, 1, True)

    def test_sets_read_only_on_specific_version(self, store, repo):
        mem = _memory("notes", "content", version=1)
        repo.get_memory_by_name.return_value = mem

        store.set_read_only("notes", True, version=3)

        repo.update_version_read_only.assert_called_once_with(mem.id, 3, True)


# ── TestResolveKeys ──


class TestResolveKeys:
    def test_delegates_to_repo(self, store, repo):
        mem = _memory("notes", "content")
        repo.resolve_memory_keys.return_value = [mem]

        result = store.resolve_keys(["notes"])

        repo.resolve_memory_keys.assert_called_once_with(["notes"])
        assert result == [mem]


# ── TestDelete ──


class TestDelete:
    def test_deletes_entire_memory(self, store, repo):
        mem = _memory("notes", "content", version=1)
        repo.get_memory_by_name.return_value = mem

        store.delete("notes")

        repo.delete_memory_v2.assert_called_once_with(mem.id)

    def test_raises_when_active_is_read_only(self, store, repo):
        mem = _memory("notes", "locked", version=1, read_only=True)
        repo.get_memory_by_name.return_value = mem

        with pytest.raises(MemoryReadOnlyError):
            store.delete("notes")

    def test_deletes_specific_version(self, store, repo):
        mem = _memory("notes", "content", version=1)
        repo.get_memory_by_name.return_value = mem

        store.delete("notes", version=2)

        repo.delete_memory_version.assert_called_once_with(mem.id, 2)

    def test_raises_when_deleting_active_version(self, store, repo):
        mem = _memory("notes", "content", version=1)
        repo.get_memory_by_name.return_value = mem

        with pytest.raises(ValueError):
            store.delete("notes", version=1)


# ── TestRename ──


class TestRename:
    def test_renames_memory(self, store, repo):
        mem = _memory("old-name", "content")
        repo.get_memory_by_name.return_value = mem

        store.rename("old-name", "new-name")

        repo.update_memory_name.assert_called_once_with(mem.id, "new-name")

    def test_raises_when_not_found(self, store, repo):
        repo.get_memory_by_name.return_value = None

        with pytest.raises(ValueError):
            store.rename("nonexistent", "new-name")


# ── TestGet ──


class TestGet:
    def test_returns_memory(self, store, repo):
        mem = _memory("notes")
        repo.get_memory_by_name.return_value = mem

        assert store.get("notes") == mem

    def test_returns_none_when_not_found(self, store, repo):
        repo.get_memory_by_name.return_value = None

        assert store.get("missing") is None


# ── TestGetVersion ──


class TestGetVersion:
    def test_returns_version(self, store, repo):
        mem = _memory("notes")
        mv = MemoryVersion(memory_id=mem.id, version=2, content="v2")
        repo.get_memory_by_name.return_value = mem
        repo.get_memory_version.return_value = mv

        result = store.get_version("notes", 2)

        assert result == mv
        repo.get_memory_version.assert_called_once_with(mem.id, 2)

    def test_returns_none_when_memory_not_found(self, store, repo):
        repo.get_memory_by_name.return_value = None

        assert store.get_version("missing", 1) is None


# ── TestListMemories ──


class TestListMemories:
    def test_delegates_to_repo(self, store, repo):
        repo.list_memories_v2.return_value = [_memory("a"), _memory("b")]

        result = store.list_memories(prefix="/", source="cogent", limit=10)

        repo.list_memories_v2.assert_called_once_with(prefix="/", source="cogent", limit=10)
        assert len(result) == 2


# ── TestHistory ──


class TestHistory:
    def test_returns_all_versions(self, store, repo):
        mem = _memory("notes")
        versions = [
            MemoryVersion(memory_id=mem.id, version=1, content="v1"),
            MemoryVersion(memory_id=mem.id, version=2, content="v2"),
        ]
        repo.get_memory_by_name.return_value = mem
        repo.list_memory_versions.return_value = versions

        result = store.history("notes")

        assert result == versions
        repo.list_memory_versions.assert_called_once_with(mem.id)

    def test_returns_empty_when_not_found(self, store, repo):
        repo.get_memory_by_name.return_value = None

        assert store.history("missing") == []

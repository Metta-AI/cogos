"""Tests for versioned memory methods on LocalRepository."""

from __future__ import annotations

from uuid import uuid4

import pytest

from cogtainer.db.local_repository import LocalRepository
from cogtainer.db.models import Memory, MemoryVersion


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(data_dir=str(tmp_path))


# ── helpers ──────────────────────────────────────────────────


def _make_memory(name: str, **kw) -> Memory:
    return Memory(name=name, **kw)


def _make_version(memory_id, version: int, **kw) -> MemoryVersion:
    return MemoryVersion(memory_id=memory_id, version=version, **kw)


# ── 1. TestInsertAndGetMemory ────────────────────────────────


class TestInsertAndGetMemory:
    def test_insert_and_get_by_name(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/test")
        mid = repo.insert_memory(mem)
        assert mid == mem.id

        found = repo.get_memory_by_name("/test")
        assert found is not None
        assert found.id == mem.id
        assert found.name == "/test"

    def test_get_nonexistent_returns_none(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_memory_by_name("/nope") is None


# ── 2. TestMemoryVersions ───────────────────────────────────


class TestMemoryVersions:
    def test_insert_and_get_version(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/v")
        repo.insert_memory(mem)
        mv = _make_version(mem.id, 1, content="hello")
        repo.insert_memory_version(mv)

        got = repo.get_memory_version(mem.id, 1)
        assert got is not None
        assert got.content == "hello"
        assert got.version == 1

    def test_get_max_version_empty(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_max_version(uuid4()) == 0

    def test_get_max_version(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/m")
        repo.insert_memory(mem)
        repo.insert_memory_version(_make_version(mem.id, 1))
        repo.insert_memory_version(_make_version(mem.id, 3))
        repo.insert_memory_version(_make_version(mem.id, 2))
        assert repo.get_max_version(mem.id) == 3

    def test_list_versions_sorted(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/s")
        repo.insert_memory(mem)
        repo.insert_memory_version(_make_version(mem.id, 3, content="c"))
        repo.insert_memory_version(_make_version(mem.id, 1, content="a"))
        repo.insert_memory_version(_make_version(mem.id, 2, content="b"))

        versions = repo.list_memory_versions(mem.id)
        assert [v.version for v in versions] == [1, 2, 3]


# ── 3. TestUpdateActiveVersion ──────────────────────────────


class TestUpdateActiveVersion:
    def test_updates_active_version(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/a", active_version=1)
        repo.insert_memory(mem)

        repo.update_active_version(mem.id, 5)
        found = repo.get_memory_by_name("/a")
        assert found is not None
        assert found.active_version == 5


# ── 4. TestUpdateReadOnly ───────────────────────────────────


class TestUpdateReadOnly:
    def test_sets_read_only(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/ro")
        repo.insert_memory(mem)
        mv = _make_version(mem.id, 1, read_only=False)
        repo.insert_memory_version(mv)

        repo.update_version_read_only(mem.id, 1, True)
        got = repo.get_memory_version(mem.id, 1)
        assert got is not None
        assert got.read_only is True


# ── 5. TestUpdateMemoryName ─────────────────────────────────


class TestUpdateMemoryName:
    def test_rename(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/old")
        repo.insert_memory(mem)

        repo.update_memory_name(mem.id, "/new")
        assert repo.get_memory_by_name("/old") is None
        found = repo.get_memory_by_name("/new")
        assert found is not None
        assert found.id == mem.id


# ── 6. TestDeleteMemory ─────────────────────────────────────


class TestDeleteMemory:
    def test_delete_removes_memory_and_versions(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/del")
        repo.insert_memory(mem)
        repo.insert_memory_version(_make_version(mem.id, 1))
        repo.insert_memory_version(_make_version(mem.id, 2))

        repo.delete_memory(mem.id)
        assert repo.get_memory_by_name("/del") is None
        assert repo.list_memory_versions(mem.id) == []


# ── 7. TestDeleteMemoryVersion ──────────────────────────────


class TestDeleteMemoryVersion:
    def test_delete_single_version(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/dv")
        repo.insert_memory(mem)
        repo.insert_memory_version(_make_version(mem.id, 1))
        repo.insert_memory_version(_make_version(mem.id, 2))

        repo.delete_memory_version(mem.id, 1)
        assert repo.get_memory_version(mem.id, 1) is None
        assert repo.get_memory_version(mem.id, 2) is not None


# ── 8. TestListMemories ─────────────────────────────────────


class TestListMemories:
    def test_filter_by_prefix(self, tmp_path):
        repo = _repo(tmp_path)
        for name in ["/a/x", "/a/y", "/b/z"]:
            m = _make_memory(name)
            repo.insert_memory(m)
            repo.insert_memory_version(_make_version(m.id, 1, source="cogent"))
            repo.update_active_version(m.id, 1)

        result = repo.list_memories(prefix="/a")
        assert len(result) == 2
        assert all(m.name.startswith("/a") for m in result)

    def test_filter_by_source(self, tmp_path):
        repo = _repo(tmp_path)
        m1 = _make_memory("/s1")
        repo.insert_memory(m1)
        repo.insert_memory_version(_make_version(m1.id, 1, source="cogtainer"))
        repo.update_active_version(m1.id, 1)

        m2 = _make_memory("/s2")
        repo.insert_memory(m2)
        repo.insert_memory_version(_make_version(m2.id, 1, source="cogent"))
        repo.update_active_version(m2.id, 1)

        result = repo.list_memories(source="cogent")
        assert len(result) == 1
        assert result[0].name == "/s2"


# ── 9. TestGetMemoryByNameWithVersions ──────────────────────


class TestGetMemoryByNameWithVersions:
    def test_versions_populated(self, tmp_path):
        repo = _repo(tmp_path)
        mem = _make_memory("/vp")
        repo.insert_memory(mem)
        repo.insert_memory_version(_make_version(mem.id, 1, content="v1"))
        repo.insert_memory_version(_make_version(mem.id, 2, content="v2"))

        found = repo.get_memory_by_name("/vp")
        assert found is not None
        assert 1 in found.versions
        assert 2 in found.versions
        assert found.versions[1].content == "v1"
        assert found.versions[2].content == "v2"


# ── 10. TestPersistence ─────────────────────────────────────


class TestPersistence:
    def test_data_survives_new_instance(self, tmp_path):
        repo1 = _repo(tmp_path)
        mem = _make_memory("/persist")
        repo1.insert_memory(mem)
        repo1.insert_memory_version(_make_version(mem.id, 1, content="saved"))

        # Create a brand new repo on the same path
        repo2 = _repo(tmp_path)
        found = repo2.get_memory_by_name("/persist")
        assert found is not None
        assert found.name == "/persist"
        versions = repo2.list_memory_versions(mem.id)
        assert len(versions) == 1
        assert versions[0].content == "saved"


# ── 11. TestResolveMemoryKeys ───────────────────────────────


class TestResolveMemoryKeys:
    def test_ancestor_init_expansion(self, tmp_path):
        repo = _repo(tmp_path)
        # Create /a/init, /a/b/init, /a/b/c
        for name in ["/a/init", "/a/b/init", "/a/b/c"]:
            m = _make_memory(name)
            repo.insert_memory(m)
            repo.insert_memory_version(_make_version(m.id, 1, content=name))
            repo.update_active_version(m.id, 1)

        result = repo.resolve_memory_keys(["/a/b/c"])
        names = [m.name for m in result]
        assert "/a/init" in names
        assert "/a/b/init" in names
        assert "/a/b/c" in names

    def test_child_init_inclusion(self, tmp_path):
        repo = _repo(tmp_path)
        # /x exists, and /x/child/init exists as a child init
        for name in ["/x", "/x/child/init", "/x/other"]:
            m = _make_memory(name)
            repo.insert_memory(m)
            repo.insert_memory_version(_make_version(m.id, 1, content=name))
            repo.update_active_version(m.id, 1)

        result = repo.resolve_memory_keys(["/x"])
        names = [m.name for m in result]
        assert "/x" in names
        assert "/x/child/init" in names
        # /x/other should NOT be included (not an /init)
        assert "/x/other" not in names

    def test_depth_sorting(self, tmp_path):
        repo = _repo(tmp_path)
        for name in ["/a/b/c", "/a/init", "/a/b/init"]:
            m = _make_memory(name)
            repo.insert_memory(m)
            repo.insert_memory_version(_make_version(m.id, 1, content=name))
            repo.update_active_version(m.id, 1)

        result = repo.resolve_memory_keys(["/a/b/c"])
        names = [m.name for m in result]
        # Should be sorted by depth: /a/init (2 slashes), /a/b/init (3), /a/b/c (3)
        assert names.index("/a/init") < names.index("/a/b/init")
        assert names.index("/a/init") < names.index("/a/b/c")

    def test_cogent_shadows_cogtainer(self, tmp_path):
        repo = _repo(tmp_path)
        # Insert cogtainer version first, then cogent with same name
        m1 = _make_memory("/shadow")
        repo.insert_memory(m1)
        repo.insert_memory_version(_make_version(m1.id, 1, source="cogtainer", content="cogtainer"))
        repo.update_active_version(m1.id, 1)

        m2 = _make_memory("/shadow")
        m2.id = uuid4()  # different id, same name
        repo.insert_memory(m2)
        repo.insert_memory_version(_make_version(m2.id, 1, source="cogent", content="cogent"))
        repo.update_active_version(m2.id, 1)

        result = repo.resolve_memory_keys(["/shadow"])
        # Should only have one entry for /shadow, the cogent one
        shadow_entries = [m for m in result if m.name == "/shadow"]
        assert len(shadow_entries) == 1
        assert shadow_entries[0].versions[shadow_entries[0].active_version].source != "cogtainer"

    def test_empty_keys(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.resolve_memory_keys([]) == []

"""Tests for Memory and MemoryVersion models."""

from uuid import UUID

from cogtainer.db.models import Memory, MemoryVersion


class TestMemoryVersion:
    def test_defaults(self):
        mv = MemoryVersion(memory_id=UUID("00000000-0000-0000-0000-000000000001"), version=1)
        assert mv.version == 1
        assert mv.read_only is False
        assert mv.content == ""
        assert mv.source == "cogent"

    def test_source_values(self):
        for source in ["polis", "cogent", "user:daveey"]:
            mv = MemoryVersion(
                memory_id=UUID("00000000-0000-0000-0000-000000000001"),
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

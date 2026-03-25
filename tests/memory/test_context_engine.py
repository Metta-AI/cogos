"""Tests for memory.context_engine.ContextEngine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cogtainer.db.models import Memory, MemoryVersion, Program
from memory.context_engine import ContextEngine


@pytest.fixture
def memory_store():
    return MagicMock()


@pytest.fixture
def engine(memory_store):
    return ContextEngine(memory_store, total_budget=50_000)


def _mem(name: str, content: str = "", includes: list[str] | None = None) -> Memory:
    """Build a Memory object with a single active version."""
    mem = Memory(name=name, active_version=1, includes=includes or [])
    mv = MemoryVersion(memory_id=mem.id, version=1, content=content or f"content of {name}")
    mem.versions[1] = mv
    return mem


def _program(content: str = "", includes: list[str] | None = None) -> tuple[Program, Memory]:
    """Build a Program backed by a memory containing the given content."""
    mem = _mem("programs/test-program", content, includes=includes)
    return Program(
        name="test-program",
        memory_id=mem.id,
    ), mem


class TestProgramContentOnly:
    def test_single_text_block(self, engine, memory_store):
        prog, mem = _program("You are a helpful bot.")
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = []

        blocks = engine.build_system_prompt(prog)

        assert len(blocks) == 1
        assert blocks[0]["text"] == "You are a helpful bot."


class TestProgramWithIncludes:
    def test_memories_wrapped_in_tags(self, engine, memory_store):
        prog, mem = _program("System prompt.", includes=["/cogtainer/tools"])
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = [
            _mem("/cogtainer/init", "base personality"),
            _mem("/cogtainer/tools/init", "tool instructions"),
        ]

        blocks = engine.build_system_prompt(prog)

        assert len(blocks) == 2
        assert blocks[0]["text"] == "System prompt."
        assert '<memory name="/cogtainer/init">' in blocks[1]["text"]
        assert "base personality" in blocks[1]["text"]
        assert '<memory name="/cogtainer/tools/init">' in blocks[1]["text"]


class TestProgramWithEvent:
    def test_event_appended(self, engine, memory_store):
        prog, mem = _program("Prompt.")
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = []

        blocks = engine.build_system_prompt(
            prog,
            event_data={"event_type": "message", "payload": {"text": "hi"}},
        )

        assert len(blocks) == 2
        assert blocks[0]["text"] == "Prompt."
        assert "Event: message" in blocks[1]["text"]
        assert '"text": "hi"' in blocks[1]["text"]


class TestAllThreeLayers:
    def test_ordering_program_memory_event(self, engine, memory_store):
        prog, mem = _program("Program.", includes=["/m"])
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = [_mem("/m")]

        blocks = engine.build_system_prompt(
            prog,
            event_data={"event_type": "tick"},
        )

        assert len(blocks) == 3
        assert blocks[0]["text"] == "Program."
        assert '<memory name="/m">' in blocks[1]["text"]
        assert "Event: tick" in blocks[2]["text"]


class TestNoMemoryId:
    def test_no_content_when_no_memory(self, engine, memory_store):
        prog = Program(name="empty")
        blocks = engine.build_system_prompt(prog)
        assert len(blocks) == 0


class TestBudgetTruncation:
    def test_memory_truncated_when_exceeding_budget(self, memory_store):
        engine = ContextEngine(memory_store, total_budget=100)
        long_content = "x" * 800

        prog, mem = _program("Short.", includes=["/big"])
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = [_mem("/big", long_content)]

        blocks = engine.build_system_prompt(prog)

        memory_block = blocks[1]["text"]
        assert memory_block.endswith("... (truncated)")
        assert len(memory_block) < len(long_content)


class TestBudgetExhaustion:
    def test_truncatable_layer_skipped_when_budget_used(self, memory_store):
        engine = ContextEngine(memory_store, total_budget=10)

        prog, mem = _program("x" * 40, includes=["/m"])
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = [_mem("/m", "some memory")]

        blocks = engine.build_system_prompt(prog)

        assert len(blocks) == 1
        assert blocks[0]["text"] == "x" * 40


class TestIncludesResolution:
    def test_resolve_includes_called_with_memory_name(self, engine, memory_store):
        prog, mem = _program("P.", includes=["/a", "/b/c"])
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = []

        engine.build_system_prompt(prog)

        memory_store.resolve_includes.assert_called_once_with("programs/test-program")


class TestPinnedVersion:
    def test_uses_pinned_version(self, engine, memory_store):
        mem = Memory(name="programs/pinned", active_version=1)
        mv1 = MemoryVersion(memory_id=mem.id, version=1, content="v1 content")
        mv2 = MemoryVersion(memory_id=mem.id, version=2, content="v2 content")
        mem.versions = {1: mv1, 2: mv2}

        prog = Program(name="pinned", memory_id=mem.id, memory_version=2)
        memory_store.get_by_id.return_value = mem
        memory_store.resolve_includes.return_value = []

        blocks = engine.build_system_prompt(prog)

        assert len(blocks) == 1
        assert blocks[0]["text"] == "v2 content"

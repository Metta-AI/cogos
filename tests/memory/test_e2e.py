"""End-to-end tests for the versioned memory system.

Exercises the full stack: MemoryStore + LocalCogtainerRepository + persistence,
including cogtainer sync logic, read-only enforcement, version management,
hierarchical key resolution, and CLI commands.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from cogtainer.db.local_repository import LocalCogtainerRepository
from cogtainer.db.models import Memory, MemoryVersion
from memory.errors import MemoryReadOnlyError
from memory.store import MemoryStore


@pytest.fixture
def store(tmp_path) -> MemoryStore:
    repo = LocalCogtainerRepository(data_dir=str(tmp_path))
    return MemoryStore(repo)


@pytest.fixture
def runner():
    return CliRunner()


# ── 1. Full lifecycle: create → version → read-only → activate ────


class TestFullLifecycle:
    def test_create_version_readonly_activate(self, store):
        # Create
        mem = store.create("/notes/todo", "buy milk")
        assert mem.name == "/notes/todo"
        assert mem.active_version == 1
        assert mem.versions[1].content == "buy milk"

        # New version (content changed)
        mv2 = store.new_version("/notes/todo", "buy milk and eggs")
        assert mv2 is not None
        assert mv2.version == 2
        assert mv2.content == "buy milk and eggs"

        # Verify active version updated
        got = store.get("/notes/todo")
        assert got.active_version == 2

        # No new version when content unchanged
        mv3 = store.new_version("/notes/todo", "buy milk and eggs")
        assert mv3 is None

        # Set read-only on version 2
        store.set_read_only("/notes/todo", True)
        got = store.get("/notes/todo")
        assert got.versions[2].read_only is True

        # Upsert blocked on read-only active version
        with pytest.raises(MemoryReadOnlyError):
            store.upsert("/notes/todo", "try to overwrite")

        # But new_version bypasses read-only (creates v3)
        mv3 = store.new_version("/notes/todo", "forced update")
        assert mv3 is not None
        assert mv3.version == 3

        # History shows all versions
        history = store.history("/notes/todo")
        assert [v.version for v in history] == [1, 2, 3]

        # Activate old version
        store.activate("/notes/todo", 1)
        got = store.get("/notes/todo")
        assert got.active_version == 1

    def test_upsert_creates_then_versions(self, store):
        # Upsert on nonexistent → create
        result = store.upsert("/x", "first")
        assert isinstance(result, Memory)
        assert result.versions[1].content == "first"

        # Upsert with same content → None
        result = store.upsert("/x", "first")
        assert result is None

        # Upsert with different content → new version
        result = store.upsert("/x", "second")
        assert isinstance(result, MemoryVersion)
        assert result.version == 2


# ── 2. Cogtainer sync logic ──────────────────────────────────────


class TestCogtainerSync:
    """Simulate what `cogos file load` does when syncing cogtainer memories."""

    def _sync_memory(self, store: MemoryStore, name: str, content: str):
        """Replicate the cogtainer sync logic from cogos CLI."""
        existing = store.get(name)
        if existing is None:
            store.create(name, content, source="cogtainer", read_only=True)
            return "created"

        mv = existing.versions.get(existing.active_version)
        if mv and mv.source.startswith("user:"):
            return "skipped_user_override"

        if mv and mv.content == content:
            return "unchanged"

        store.new_version(name, content, source="cogtainer", read_only=True)
        return "updated"

    def test_new_memory_created_readonly(self, store):
        result = self._sync_memory(store, "/cogtainer/init", "base personality")
        assert result == "created"
        mem = store.get("/cogtainer/init")
        assert mem.versions[1].source == "cogtainer"
        assert mem.versions[1].read_only is True

    def test_user_override_skipped(self, store):
        # Create cogtainer version first
        store.create("/cogtainer/init", "cogtainer content", source="cogtainer", read_only=True)
        # User overrides with new_version (bypasses read-only)
        store.new_version("/cogtainer/init", "user override", source="user:dave")
        # Active version is now user's
        mem = store.get("/cogtainer/init")
        assert mem.versions[mem.active_version].source == "user:dave"

        # Cogtainer sync should skip
        result = self._sync_memory(store, "/cogtainer/init", "updated cogtainer content")
        assert result == "skipped_user_override"

        # Content unchanged
        mem = store.get("/cogtainer/init")
        assert mem.versions[mem.active_version].content == "user override"

    def test_unchanged_content_skipped(self, store):
        self._sync_memory(store, "/cogtainer/tools", "tool instructions")
        result = self._sync_memory(store, "/cogtainer/tools", "tool instructions")
        assert result == "unchanged"

        # Still only one version
        history = store.history("/cogtainer/tools")
        assert len(history) == 1

    def test_changed_cogtainer_content_creates_new_version(self, store):
        self._sync_memory(store, "/cogtainer/tools", "v1 tools")
        result = self._sync_memory(store, "/cogtainer/tools", "v2 tools")
        assert result == "updated"

        mem = store.get("/cogtainer/tools")
        assert mem.active_version == 2
        assert mem.versions[2].content == "v2 tools"
        assert mem.versions[2].source == "cogtainer"
        assert mem.versions[2].read_only is True

    def test_cogent_override_not_skipped(self, store):
        """Cogtainer sync should update when active version is from cogent."""
        store.create("/cogtainer/init", "cogtainer v1", source="cogtainer", read_only=True)
        store.new_version("/cogtainer/init", "cogent modified", source="cogent")

        # Active is cogent, NOT user:* so sync should proceed
        result = self._sync_memory(store, "/cogtainer/init", "cogtainer v2")
        assert result == "updated"

        mem = store.get("/cogtainer/init")
        assert mem.versions[mem.active_version].source == "cogtainer"


# ── 3. Delete operations ─────────────────────────────────────────


class TestDeleteOperations:
    def test_delete_entire_memory(self, store):
        store.create("/del/me", "content")
        store.delete("/del/me")
        assert store.get("/del/me") is None

    def test_delete_read_only_blocked(self, store):
        store.create("/del/ro", "locked", read_only=True)
        with pytest.raises(MemoryReadOnlyError):
            store.delete("/del/ro")

    def test_delete_specific_version(self, store):
        store.create("/del/v", "v1")
        store.new_version("/del/v", "v2")
        store.delete("/del/v", version=1)

        history = store.history("/del/v")
        assert len(history) == 1
        assert history[0].version == 2

    def test_cannot_delete_active_version(self, store):
        store.create("/del/active", "v1")
        with pytest.raises(ValueError, match="cannot delete active version"):
            store.delete("/del/active", version=1)


# ── 4. Rename ────────────────────────────────────────────────────


class TestRename:
    def test_rename_preserves_versions(self, store):
        store.create("/old/name", "v1")
        store.new_version("/old/name", "v2")

        store.rename("/old/name", "/new/name")

        assert store.get("/old/name") is None
        got = store.get("/new/name")
        assert got is not None
        assert got.active_version == 2
        history = store.history("/new/name")
        assert len(history) == 2


# ── 5. Persistence across LocalCogtainerRepository instances ──────────────


class TestPersistence:
    def test_full_state_survives_reload(self, tmp_path):
        # Create with one instance
        repo1 = LocalCogtainerRepository(data_dir=str(tmp_path))
        store1 = MemoryStore(repo1)

        store1.create("/persist/a", "content a", source="cogtainer", read_only=True)
        store1.create("/persist/b", "content b v1")
        store1.new_version("/persist/b", "content b v2")
        store1.set_read_only("/persist/b", True, version=1)

        # Read with a new instance
        repo2 = LocalCogtainerRepository(data_dir=str(tmp_path))
        store2 = MemoryStore(repo2)

        # Memory a
        a = store2.get("/persist/a")
        assert a is not None
        assert a.versions[1].content == "content a"
        assert a.versions[1].read_only is True
        assert a.versions[1].source == "cogtainer"

        # Memory b
        b = store2.get("/persist/b")
        assert b is not None
        assert b.active_version == 2
        assert b.versions[2].content == "content b v2"

        # Version 1 of b is read-only
        b_history = store2.history("/persist/b")
        v1 = [v for v in b_history if v.version == 1][0]
        assert v1.read_only is True


# ── 6. Hierarchical key resolution ──────────────────────────────


class TestResolveKeys:
    def test_ancestor_init_expansion(self, store):
        store.create("/a/init", "base")
        store.create("/a/b/init", "level 2")
        store.create("/a/b/c", "leaf")

        result = store.resolve_keys(["/a/b/c"])
        names = [m.name for m in result]
        assert "/a/init" in names
        assert "/a/b/init" in names
        assert "/a/b/c" in names

    def test_child_init_included(self, store):
        store.create("/x", "parent")
        store.create("/x/child/init", "child init")
        store.create("/x/other", "other")

        result = store.resolve_keys(["/x"])
        names = [m.name for m in result]
        assert "/x" in names
        assert "/x/child/init" in names
        assert "/x/other" not in names

    def test_depth_sorted(self, store):
        store.create("/a/init", "base")
        store.create("/a/b/init", "mid")
        store.create("/a/b/c", "leaf")

        result = store.resolve_keys(["/a/b/c"])
        names = [m.name for m in result]
        assert names.index("/a/init") < names.index("/a/b/init")
        assert names.index("/a/init") < names.index("/a/b/c")


# ── 7. Context engine integration ───────────────────────────────


class TestContextEngineIntegration:
    def test_build_system_prompt_with_versioned_memories(self, store):
        from cogtainer.db.models import Program
        from memory.context_engine import ContextEngine

        # Create program content as a memory with includes
        prog_mem = store.create("programs/test", "System prompt.")
        store.update_includes("programs/test", ["/cogtainer/tools"])
        store.create("/cogtainer/init", "You are a helpful assistant.")
        store.create("/cogtainer/tools/init", "Use these tools: hammer, wrench")

        engine = ContextEngine(store, total_budget=50_000)
        program = Program(
            name="test",
            memory_id=prog_mem.id,
        )

        blocks = engine.build_system_prompt(program)
        assert len(blocks) >= 2
        # Program block
        assert blocks[0]["text"] == "System prompt."
        # Memory block contains resolved memories
        mem_text = blocks[1]["text"]
        assert "You are a helpful assistant." in mem_text
        assert "Use these tools: hammer, wrench" in mem_text


# ── 8. CLI commands via Click test runner ────────────────────────


class TestCLI:
    """Test CLI commands using CliRunner with a patched store."""

    @pytest.fixture(autouse=True)
    def patch_store(self, tmp_path, monkeypatch):
        """Patch _get_store to use a LocalCogtainerRepository backed by tmp_path."""
        repo = LocalCogtainerRepository(data_dir=str(tmp_path))
        s = MemoryStore(repo)
        self._store = s
        self._tmp_path = tmp_path

        import memory.cli as cli_mod

        monkeypatch.setattr(cli_mod, "_get_store", lambda: s)

    def test_put_and_list(self, runner):
        from memory.cli import memory

        # Create a markdown file
        md_dir = self._tmp_path / "mds"
        md_dir.mkdir()
        (md_dir / "hello.md").write_text("Hello world!")

        # Put it
        result = runner.invoke(memory, ["put", str(md_dir), "-p", "/test"])
        assert result.exit_code == 0
        assert "1 created" in result.output

        # List it
        result = runner.invoke(memory, ["list"])
        assert result.exit_code == 0
        assert "/test/hello" in result.output

    def test_get_and_history(self, runner):
        from memory.cli import memory

        self._store.create("/cli/test", "version 1 content")
        self._store.new_version("/cli/test", "version 2 content")

        # Get (shows active version)
        result = runner.invoke(memory, ["get", "/cli/test"])
        assert result.exit_code == 0
        assert "version 2 content" in result.output
        assert "Active version: 2" in result.output

        # Get specific version
        result = runner.invoke(memory, ["get", "/cli/test", "-v", "1"])
        assert result.exit_code == 0
        assert "version 1 content" in result.output

        # History
        result = runner.invoke(memory, ["history", "/cli/test"])
        assert result.exit_code == 0
        assert "1" in result.output
        assert "2" in result.output

    def test_activate_command(self, runner):
        from memory.cli import memory

        self._store.create("/cli/act", "v1")
        self._store.new_version("/cli/act", "v2")

        result = runner.invoke(memory, ["activate", "/cli/act", "1"])
        assert result.exit_code == 0
        assert "Activated version 1" in result.output

        mem = self._store.get("/cli/act")
        assert mem is not None
        assert mem.active_version == 1

    def test_set_ro_and_delete_blocked(self, runner):
        from memory.cli import memory

        self._store.create("/cli/ro", "locked content")

        # Set read-only
        result = runner.invoke(memory, ["set-ro", "/cli/ro"])
        assert result.exit_code == 0
        assert "read-only" in result.output

        # Delete should fail
        result = runner.invoke(memory, ["delete", "/cli/ro", "-y"])
        assert result.exit_code != 0
        assert "read-only" in result.output

    def test_rename_command(self, runner):
        from memory.cli import memory

        self._store.create("/cli/old", "content")

        result = runner.invoke(memory, ["rename", "/cli/old", "/cli/new"])
        assert result.exit_code == 0
        assert "Renamed" in result.output

        assert self._store.get("/cli/old") is None
        assert self._store.get("/cli/new") is not None

    def test_status_command(self, runner):
        from memory.cli import memory

        self._store.create("/s1", "c1", source="cogtainer", read_only=True)
        self._store.create("/s2", "c2", source="cogent")
        self._store.create("/s3", "c3", source="user:dave")

        result = runner.invoke(memory, ["status"])
        assert result.exit_code == 0
        assert "Total memories: 3" in result.output
        assert "cogtainer: 1" in result.output
        assert "cogent: 1" in result.output
        assert "user:dave: 1" in result.output
        assert "Read-only: 1" in result.output

    def test_put_unchanged_skipped(self, runner):
        from memory.cli import memory

        md_dir = self._tmp_path / "mds2"
        md_dir.mkdir()
        (md_dir / "note.md").write_text("same content")

        # First put
        result = runner.invoke(memory, ["put", str(md_dir), "-p", "/t"])
        assert "1 created" in result.output

        # Second put (unchanged)
        result = runner.invoke(memory, ["put", str(md_dir), "-p", "/t"])
        assert "1 unchanged" in result.output
        assert "0 created" in result.output

    def test_put_force_bypasses_readonly(self, runner):
        from memory.cli import memory

        self._store.create("/t/note", "original", source="cogtainer", read_only=True)

        md_dir = self._tmp_path / "mds3"
        md_dir.mkdir()
        (md_dir / "note.md").write_text("updated content")

        # Without --force: should fail
        result = runner.invoke(memory, ["put", str(md_dir), "-p", "/t"])
        assert "read-only" in result.output

        # With --force: should succeed
        result = runner.invoke(memory, ["put", str(md_dir), "-p", "/t", "-f"])
        assert result.exit_code == 0
        assert "1 updated" in result.output

        mem = self._store.get("/t/note")
        assert mem is not None
        assert mem.active_version == 2

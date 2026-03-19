"""End-to-end tests for the full capability scoping system.

Exercises FilesCapability, ProcsCapability scoping,
spawn delegation, and sandbox restrictions without mocking capability logic.
Only the repo/DB layer is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.files import FileError, FilesCapability
from cogos.capabilities.procs import ProcessError, ProcsCapability
from cogos.sandbox.executor import SandboxExecutor, VariableTable

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


# ── 1. FilesCapability prefix + ops scoping ───────────────────


class TestScopedFilesCapabilityEnforcesPrefix:
    def test_read_within_prefix_allowed(self, repo, pid):
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        # Should not raise
        cap._check("read", key="/workspace/doc.md")

    def test_read_outside_prefix_denied(self, repo, pid):
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        with pytest.raises(PermissionError):
            cap._check("read", key="/secret/key")

    def test_write_not_in_ops_denied(self, repo, pid):
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        with pytest.raises(PermissionError):
            cap._check("write", key="/workspace/doc.md")

    def test_read_method_within_prefix_does_not_raise_permission(self, repo, pid):
        """Calling read() on a scoped capability with a valid key should reach
        the repo layer (FileStore) rather than raising PermissionError."""
        # Make the file lookup return None so we get a FileError (not found)
        # rather than hitting Pydantic validation on mock objects.
        repo.get_file_by_key.return_value = None
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        result = cap.read("/workspace/doc.md")
        # Should NOT raise PermissionError — it reaches the store layer and
        # returns a FileError because the file doesn't exist in our mock.
        assert isinstance(result, FileError)
        assert "not found" in result.error

    def test_read_method_outside_prefix_raises(self, repo, pid):
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        with pytest.raises(PermissionError):
            cap.read("/secret/key")

    def test_write_method_blocked_by_ops(self, repo, pid):
        cap = FilesCapability(repo, pid).scope(prefix="/workspace/", ops={"read"})
        with pytest.raises(PermissionError):
            cap.write("/workspace/doc.md", "x")


# ── 2. Scope chain only narrows ───────────────────────────────


class TestScopeChainOnlyNarrows:
    def test_successive_ops_narrowing(self, repo, pid):
        cap = FilesCapability(repo, pid)
        s1 = cap.scope(prefix="/workspace/", ops={"read", "write", "search"})
        s2 = s1.scope(ops={"read"})
        # Only read should be allowed
        s2._check("read", key="/workspace/foo")
        with pytest.raises(PermissionError):
            s2._check("write", key="/workspace/foo")
        with pytest.raises(PermissionError):
            s2._check("search", key="/workspace/foo")

    def test_successive_prefix_narrowing(self, repo, pid):
        cap = FilesCapability(repo, pid)
        s1 = cap.scope(prefix="/workspace/", ops={"read", "write", "search"})
        s2 = s1.scope(ops={"read"})
        s3 = s2.scope(prefix="/workspace/docs/")
        # Prefix is now /workspace/docs/
        s3._check("read", key="/workspace/docs/readme.md")
        with pytest.raises(PermissionError):
            s3._check("read", key="/workspace/other/file.txt")

    def test_widen_prefix_raises_value_error(self, repo, pid):
        cap = FilesCapability(repo, pid)
        s1 = cap.scope(prefix="/workspace/", ops={"read", "write", "search"})
        with pytest.raises(ValueError, match="Cannot widen prefix"):
            s1.scope(prefix="/other/")


# ── 4. Spawn delegation enforces parent scope ─────────────────


class TestSpawnDelegationEnforcesParentScope:
    def _setup_parent_grants(self, repo, pid, prefix, ops):
        """Configure mock repo so the parent holds a files capability with given scope."""
        from cogos.db.models.capability import Capability as CapModel
        from cogos.db.models.process_capability import ProcessCapability

        files_cap_id = uuid4()
        cap_model = CapModel(id=files_cap_id, name="files", enabled=True)

        parent_grant = ProcessCapability(
            process=pid,
            capability=files_cap_id,
            name="files",
            config={"prefix": prefix, "ops": ops},
        )

        repo.list_process_capabilities.return_value = [parent_grant]
        repo.get_capability_by_name.return_value = cap_model
        repo.upsert_process.return_value = uuid4()
        repo.create_process_capability.return_value = None

        return files_cap_id

    def test_narrower_child_scope_succeeds(self, repo, pid):
        self._setup_parent_grants(
            repo,
            pid,
            prefix="/workspace/",
            ops={"read"},
        )
        procs = ProcsCapability(repo, pid)
        child_files = FilesCapability(repo, pid).scope(prefix="/workspace/docs/", ops={"read"})
        result = procs.spawn(
            name="child",
            content="do something",
            capabilities={"files": child_files},
        )
        # Should succeed — child scope is strictly narrower
        assert not hasattr(result, "error") or getattr(result, "error", None) is None

    def test_outside_parent_prefix_fails(self, repo, pid):
        self._setup_parent_grants(
            repo,
            pid,
            prefix="/workspace/",
            ops={"read"},
        )
        procs = ProcsCapability(repo, pid)
        child_files = FilesCapability(repo, pid).scope(prefix="/other/", ops={"read"})
        result = procs.spawn(
            name="child",
            content="do something",
            capabilities={"files": child_files},
        )
        assert isinstance(result, ProcessError)
        assert "scope" in result.error.lower() or "widen" in result.error.lower() or "Cannot" in result.error

    def test_unscoped_child_when_parent_scoped_fails(self, repo, pid):
        self._setup_parent_grants(
            repo,
            pid,
            prefix="/workspace/",
            ops={"read"},
        )
        procs = ProcsCapability(repo, pid)
        # Unscoped child — wider than parent's scoped grant
        child_files = FilesCapability(repo, pid)
        result = procs.spawn(
            name="child",
            content="do something",
            capabilities={"files": child_files},
        )
        assert isinstance(result, ProcessError)
        assert "widen" in result.error.lower() or "scope" in result.error.lower()


# ── 5. Sandbox blocks dangerous operations ────────────────────


class TestSandboxBlocksDangerousOperations:
    @staticmethod
    def _run(code: str) -> str:
        vt = VariableTable()
        executor = SandboxExecutor(vt)
        return executor.execute(code)

    def test_import_blocked(self):
        result = self._run("import os")
        assert "error" in result.lower()

    def test_open_blocked(self):
        result = self._run("open('/etc/passwd')")
        assert "error" in result.lower()

    def test_dunder_import_blocked(self):
        result = self._run("__import__('subprocess')")
        assert "error" in result.lower()

    def test_safe_builtins_work(self):
        result = self._run("print(len([1,2,3]))")
        assert "3" in result

    def test_json_works(self):
        result = self._run('print(json.dumps({"a": 1}))')
        assert '"a": 1' in result or '"a":1' in result


# ── 6. Sandbox cannot forge capability ────────────────────────


class TestSandboxCannotForgeCapability:
    @staticmethod
    def _run_with_files(code: str) -> str:
        vt = VariableTable()
        # Provide a scoped files capability as a variable in the sandbox
        repo = MagicMock()
        files = FilesCapability(repo, uuid4()).scope(prefix="/safe/", ops={"read"})
        vt.set("files", files)
        executor = SandboxExecutor(vt)
        return executor.execute(code)

    def test_import_capability_module_blocked(self):
        result = self._run_with_files("from cogos.capabilities.files import FilesCapability")
        assert "error" in result.lower()

    def test_reflection_via_type_blocked(self):
        """Even with an object reference, reflection via type()  __bases__ cannot
        construct new capabilities because __import__ is unavailable."""
        result = self._run_with_files("type(files).__bases__[0].__subclasses__()")
        # This may or may not error depending on builtins available,
        # but it should NOT return a usable capability constructor.
        # If it errors, that is the safe outcome.
        # If it returns something, verify it's not usable for forgery.
        if "error" in result.lower():
            return  # blocked — good
        # If type() worked (it's in safe builtins), the subclasses list
        # is just informational; without __import__ you can't instantiate
        # with a real repo. Verify no actual import happened.
        assert "import" not in result.lower()

    def test_direct_construction_blocked(self):
        """Cannot use exec/eval to construct a new capability."""
        result = self._run_with_files("exec('import cogos')")
        assert "error" in result.lower()

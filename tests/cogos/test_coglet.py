"""Tests for the coglet core module."""

from __future__ import annotations

import json

import pytest

from cogos.coglet import (
    CogletMeta,
    LogEntry,
    PatchInfo,
    TestResult,
    apply_diff,
    delete_file_tree,
    read_file_tree,
    run_tests,
    write_file_tree,
)
from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestCogletMeta:
    def test_defaults(self):
        m = CogletMeta(name="widget", test_command="pytest")
        assert m.name == "widget"
        assert m.test_command == "pytest"
        assert m.executor == "subprocess"
        assert m.timeout_seconds == 60
        assert m.version == 0
        assert m.patches == {}
        # id should be a valid uuid string
        assert len(m.id) == 36
        # created_at should be an ISO timestamp
        assert "T" in m.created_at

    def test_json_roundtrip(self):
        m = CogletMeta(name="widget", test_command="pytest")
        data = m.model_dump_json()
        m2 = CogletMeta.model_validate_json(data)
        assert m == m2

    def test_patches_dict(self):
        p = PatchInfo(base_version=1, test_passed=True, test_output="ok")
        m = CogletMeta(name="w", test_command="pytest", patches={"p1": p})
        assert m.patches["p1"].test_passed is True


class TestPatchInfo:
    def test_creation(self):
        p = PatchInfo(base_version=3, test_passed=False, test_output="fail")
        assert p.base_version == 3
        assert p.test_passed is False
        assert p.test_output == "fail"
        assert "T" in p.created_at

    def test_defaults(self):
        p = PatchInfo(base_version=0, test_passed=True)
        assert p.test_output == ""


class TestLogEntry:
    def test_creation(self):
        e = LogEntry(action="proposed", patch_id="abc")
        assert e.action == "proposed"
        assert e.patch_id == "abc"
        assert e.version is None
        assert "T" in e.timestamp


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


class TestRunTests:
    def test_passing(self):
        result = run_tests(
            "echo hello",
            {"main.py": "print('hello')"},
        )
        assert result.passed is True
        assert result.exit_code == 0
        assert "hello" in result.output

    def test_failing(self):
        result = run_tests(
            "exit 1",
            {"main.py": "x = 1"},
        )
        assert result.passed is False
        assert result.exit_code == 1

    def test_timeout(self):
        result = run_tests(
            "sleep 10",
            {},
            timeout_seconds=1,
        )
        assert result.passed is False
        assert result.exit_code == -1

    def test_files_materialized(self):
        result = run_tests(
            "cat sub/data.txt",
            {"sub/data.txt": "content123"},
        )
        assert result.passed is True
        assert "content123" in result.output


# ---------------------------------------------------------------------------
# File tree helpers
# ---------------------------------------------------------------------------


class TestFileTree:
    def _store(self, tmp_path) -> FileStore:
        repo = LocalRepository(str(tmp_path))
        return FileStore(repo)

    def test_write_read_roundtrip(self, tmp_path):
        store = self._store(tmp_path)
        files = {"main.py": "print(1)", "lib/util.py": "x = 2"}
        write_file_tree(store, "cog1", "main", files)
        result = read_file_tree(store, "cog1", "main")
        assert result == files

    def test_read_nonexistent_returns_empty(self, tmp_path):
        store = self._store(tmp_path)
        result = read_file_tree(store, "missing", "main")
        assert result == {}

    def test_write_read_patch_branch(self, tmp_path):
        store = self._store(tmp_path)
        main_files = {"main.py": "v1"}
        patch_files = {"main.py": "v2", "new.py": "added"}
        write_file_tree(store, "cog1", "main", main_files)
        write_file_tree(store, "cog1", "patch/p1", patch_files)

        assert read_file_tree(store, "cog1", "main") == main_files
        assert read_file_tree(store, "cog1", "patch/p1") == patch_files

    def test_delete_file_tree(self, tmp_path):
        store = self._store(tmp_path)
        write_file_tree(store, "cog1", "main", {"a.py": "1", "b.py": "2"})
        count = delete_file_tree(store, "cog1", "main")
        assert count == 2
        assert read_file_tree(store, "cog1", "main") == {}


# ---------------------------------------------------------------------------
# Diff application
# ---------------------------------------------------------------------------


class TestApplyDiff:
    def test_modify_file(self):
        files = {"hello.py": "line1\nline2\nline3"}
        diff = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3"
        )
        result = apply_diff(files, diff)
        assert result["hello.py"] == "line1\nline2_modified\nline3"

    def test_add_file(self):
        files = {"existing.py": "code"}
        diff = (
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+hello\n"
            "+world"
        )
        result = apply_diff(files, diff)
        assert "new.py" in result
        assert result["new.py"] == "hello\nworld"
        assert result["existing.py"] == "code"

    def test_delete_file(self):
        files = {"remove.py": "gone", "keep.py": "stay"}
        diff = (
            "--- a/remove.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-gone"
        )
        result = apply_diff(files, diff)
        assert "remove.py" not in result
        assert result["keep.py"] == "stay"

    def test_invalid_diff_raises(self):
        with pytest.raises(ValueError):
            apply_diff({}, "not a diff at all")

    def test_modify_nonexistent_raises(self):
        diff = (
            "--- a/missing.py\n"
            "+++ b/missing.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new"
        )
        with pytest.raises(ValueError, match="not in tree"):
            apply_diff({}, diff)

"""Tests for FileCapability, FileVersionCapability, and DirCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.file_cap import (
    DirCapability,
    FileCapability,
    FileVersionCapability,
)
from cogos.capabilities.files import FileContent, FileError
from cogos.db.models import File, FileVersion


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


# ── FileCapability ──────────────────────────────────────────


class TestFileCapabilityScoping:
    def test_scoped_key_cannot_change(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with pytest.raises(ValueError):
            scoped.scope(key="/config/other")

    def test_scoped_key_same_is_ok(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        again = scoped.scope(key="/config/system")
        assert again._scope["key"] == "/config/system"

    def test_ops_intersect(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(ops={"read", "write", "delete", "get_metadata"})
        narrower = scoped.scope(ops={"read", "write"})
        assert narrower._scope["ops"] == {"read", "write"}

    def test_ops_empty_intersection(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(ops={"read"})
        narrower = scoped.scope(ops={"write"})
        assert narrower._scope["ops"] == set()

    def test_check_denies_wrong_key(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with pytest.raises(PermissionError):
            scoped.read("/config/other")

    def test_check_denies_wrong_op(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="/config/system", ops={"read"})
        with pytest.raises(PermissionError):
            scoped.write("/config/system", "data")

    def test_check_allows_correct_key_and_op(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = None
            result = scoped.read("/config/system")
            assert isinstance(result, FileError)

    def test_all_ops(self):
        assert FileCapability.ALL_OPS == {"read", "write", "append", "edit"}


# ── FileVersionCapability ───────────────────────────────────


class TestFileVersionCapabilityScoping:
    def test_scoped_key_cannot_change(self, repo, pid):
        cap = FileVersionCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with pytest.raises(ValueError):
            scoped.scope(key="/config/other")

    def test_ops_intersect(self, repo, pid):
        cap = FileVersionCapability(repo, pid)
        scoped = cap.scope(ops={"add", "list", "get", "update"})
        narrower = scoped.scope(ops={"add", "list"})
        assert narrower._scope["ops"] == {"add", "list"}

    def test_check_denies_wrong_key(self, repo, pid):
        cap = FileVersionCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with pytest.raises(PermissionError):
            scoped.list("/config/other")

    def test_check_denies_wrong_op(self, repo, pid):
        cap = FileVersionCapability(repo, pid)
        scoped = cap.scope(key="/config/system", ops={"list"})
        with pytest.raises(PermissionError):
            scoped.add("/config/system", "data")

    def test_check_allows_correct_key_and_op(self, repo, pid):
        cap = FileVersionCapability(repo, pid)
        scoped = cap.scope(key="/config/system")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.history.return_value = []
            result = scoped.list("/config/system")
            assert isinstance(result, list)

    def test_all_ops(self):
        assert FileVersionCapability.ALL_OPS == {"add", "list"}


# ── DirCapability ───────────────────────────────────────────


class TestDirCapabilityScoping:
    def test_prefix_cannot_widen(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        with pytest.raises(ValueError):
            scoped.scope(prefix="/")

    def test_prefix_can_narrow(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        narrower = scoped.scope(prefix="/workspace/subdir/")
        assert narrower._scope["prefix"] == "/workspace/subdir/"

    def test_prefix_rejects_different_path(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        with pytest.raises(ValueError):
            scoped.scope(prefix="/other/")

    def test_full_key_prepends_prefix(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        assert scoped._full_key("file.txt") == "/workspace/file.txt"

    def test_full_key_does_not_double_prefix(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        assert scoped._full_key("/workspace/file.txt") == "/workspace/file.txt"

    def test_get_returns_file_capability(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        fc = scoped.get("file.txt")
        assert isinstance(fc, FileCapability)
        assert fc._scope["key"] == "/workspace/file.txt"

    def test_list_uses_prefix_scope(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.list_files.return_value = []
            result = scoped.list()
            assert isinstance(result, list)

    def test_ops_intersect(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list", "get"})
        narrower = scoped.scope(ops={"list"})
        assert narrower._scope["ops"] == {"list"}

    def test_all_ops(self):
        assert DirCapability.ALL_OPS == {"list", "get", "grep", "glob", "tree"}


# ── DirCapability grep/glob/tree ───────────────────────────


class TestDirGrepGlobTree:
    def test_grep_returns_results(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.grep_files.return_value = [("/workspace/main.py", "line1\n# TODO fix\nline3")]
        results = scoped.grep("TODO")
        assert len(results) == 1
        assert results[0].key == "/workspace/main.py"
        assert results[0].matches[0].line == 1
        assert "TODO" in results[0].matches[0].text

    def test_grep_respects_prefix_scope(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.grep_files.return_value = []
        scoped.grep("pattern")
        repo.grep_files.assert_called_once_with("pattern", prefix="/workspace/", limit=100)

    def test_grep_with_context(self, repo, pid):
        cap = DirCapability(repo, pid)
        repo.grep_files.return_value = [("file.py", "a\nb\nTODO fix\nd\ne")]
        results = cap.grep("TODO", context=1)
        m = results[0].matches[0]
        assert m.before == ["b"]
        assert m.after == ["d"]

    def test_grep_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.grep("pattern")

    def test_glob_returns_keys(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.glob_files.return_value = ["/workspace/config.yaml"]
        results = scoped.glob("*.yaml")
        assert len(results) == 1
        assert results[0].key == "/workspace/config.yaml"

    def test_glob_respects_prefix_scope(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.glob_files.return_value = []
        scoped.glob("**/*.py")
        repo.glob_files.assert_called_once_with("**/*.py", prefix="/workspace/", limit=50)

    def test_glob_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.glob("*.py")

    def test_tree_returns_string(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/ws/")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            from cogos.db.models import File

            store.list_files.return_value = [
                File(key="/ws/a.py"),
                File(key="/ws/sub/b.py"),
                File(key="/ws/sub/c.py"),
            ]
            result = scoped.tree()
            assert "a.py" in result
            assert "sub/" in result

    def test_tree_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.tree()


# ── FileCapability sliced read / head / tail ───────────────


class TestFileSlicedRead:
    def _setup_file(self, repo, key="test.py"):
        content = "\n".join(f"line {i}" for i in range(100))
        f = File(key=key)
        fv = FileVersion(file_id=f.id, version=1, content=content, source="agent", is_active=True)
        repo.get_active_file_version.return_value = fv
        return f, fv, content

    def test_read_with_offset_limit(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py", offset=10, limit=5)
            assert isinstance(result, FileContent)
            assert result.total_lines == 100
            lines = result.content.split("\n")
            assert len(lines) == 5
            assert lines[0] == "line 10"

    def test_read_no_slice_includes_total_lines(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py")
            assert not isinstance(result, FileError)
            assert result.total_lines == 100

    def test_head(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.head("test.py", n=3)
            assert not isinstance(result, FileError)
            lines = result.content.split("\n")
            assert len(lines) == 3
            assert lines[0] == "line 0"

    def test_tail(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.tail("test.py", n=3)
            assert not isinstance(result, FileError)
            lines = result.content.split("\n")
            assert len(lines) == 3
            assert lines[-1] == "line 99"

    def test_read_negative_offset(self, repo, pid):
        """Negative offset reads from end, like tail."""
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py", offset=-5)
            assert not isinstance(result, FileError)
            lines = result.content.split("\n")
            assert len(lines) == 5
            assert lines[-1] == "line 99"


# ── FileCapability edit ────────────────────────────────────


class TestFileEdit:
    def _setup_file(self, repo, key="test.py", content="hello world\nfoo bar\nbaz"):
        f = File(key=key)
        fv = FileVersion(file_id=f.id, version=1, content=content, source="agent", is_active=True)
        repo.get_active_file_version.return_value = fv
        return f, fv

    def test_edit_replaces_unique_match(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            store.upsert.return_value = fv
            _result = cap.edit("test.py", "foo bar", "replaced")
            store.upsert.assert_called_once()
            new_content = store.upsert.call_args[0][1]
            assert "replaced" in new_content
            assert "foo bar" not in new_content

    def test_edit_fails_if_not_found(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "nonexistent", "replaced")
            assert isinstance(result, FileError)
            assert "not found" in result.error

    def test_edit_fails_if_not_unique(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo, content="aaa\naaa\nbbb")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "aaa", "replaced")
            assert isinstance(result, FileError)
            assert "not unique" in result.error

    def test_edit_replace_all(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo, content="aaa\naaa\nbbb")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            store.upsert.return_value = fv
            _result = cap.edit("test.py", "aaa", "xxx", replace_all=True)
            new_content = store.upsert.call_args[0][1]
            assert new_content == "xxx\nxxx\nbbb"

    def test_edit_replace_all_zero_matches(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "nonexistent", "xxx", replace_all=True)
            assert isinstance(result, FileError)

    def test_edit_denied_without_op(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="test.py", ops={"read"})
        with pytest.raises(PermissionError):
            scoped.edit("test.py", "old", "new")

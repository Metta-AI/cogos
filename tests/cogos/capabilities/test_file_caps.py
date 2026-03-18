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
from cogos.capabilities.files import FileError


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
        assert FileCapability.ALL_OPS == {"read", "write", "append"}


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
        repo.grep_files.return_value = [
            ("/workspace/main.py", "line1\n# TODO fix\nline3")
        ]
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
        repo.grep_files.assert_called_once_with(
            "pattern", prefix="/workspace/", limit=100
        )

    def test_grep_with_context(self, repo, pid):
        cap = DirCapability(repo, pid)
        repo.grep_files.return_value = [
            ("file.py", "a\nb\nTODO fix\nd\ne")
        ]
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
        repo.glob_files.assert_called_once_with(
            "**/*.py", prefix="/workspace/", limit=50
        )

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

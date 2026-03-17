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
        assert DirCapability.ALL_OPS == {"list", "get"}

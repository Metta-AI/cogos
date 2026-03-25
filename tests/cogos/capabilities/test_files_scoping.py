"""Tests for FilesCapability scoping: prefix and ops narrowing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.files import FileError, FilesCapability


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


@pytest.fixture
def cap(repo, pid):
    return FilesCapability(repo, pid)


def _mock_file_store():
    """Patch FileStore so read/write/search don't hit real DB."""
    patcher = patch("cogos.capabilities.files.FileStore")
    mock_cls = patcher.start()
    store = mock_cls.return_value
    # get() returns None so read() returns FileError (not PermissionError)
    store.get.return_value = None
    # upsert() returns None so write() returns a result
    store.upsert.return_value = None
    # list_files() returns empty list
    store.list_files.return_value = []
    return patcher, store


class TestUnscopedAccess:
    def test_unscoped_allows_any_key_read(self, cap):
        """Unscoped capability allows read of any key."""
        patcher, _ = _mock_file_store()
        try:
            result = cap.read("any/key/here")
            assert isinstance(result, FileError)
        finally:
            patcher.stop()

    def test_unscoped_allows_any_key_write(self, cap):
        patcher, _ = _mock_file_store()
        try:
            result = cap.write("any/key/here", "content")
            assert result is not None
        finally:
            patcher.stop()

    def test_unscoped_allows_search(self, cap):
        patcher, _ = _mock_file_store()
        try:
            result = cap.search("any/prefix")
            assert isinstance(result, list)
        finally:
            patcher.stop()


class TestScopedPrefix:
    def test_prefix_allows_matching_key_read(self, cap):
        patcher, _ = _mock_file_store()
        try:
            scoped = cap.scope(prefix="config/")
            result = scoped.read("config/system")
            assert isinstance(result, FileError)  # no PermissionError
        finally:
            patcher.stop()

    def test_prefix_allows_matching_key_write(self, cap):
        patcher, _ = _mock_file_store()
        try:
            scoped = cap.scope(prefix="config/")
            result = scoped.write("config/system", "data")
            assert result is not None
        finally:
            patcher.stop()

    def test_prefix_denies_outside_key_read(self, cap):
        scoped = cap.scope(prefix="config/")
        with pytest.raises(PermissionError):
            scoped.read("notes/daily")

    def test_prefix_denies_outside_key_write(self, cap):
        scoped = cap.scope(prefix="config/")
        with pytest.raises(PermissionError):
            scoped.write("notes/daily", "data")

    def test_prefix_denies_outside_search(self, cap):
        scoped = cap.scope(prefix="config/")
        with pytest.raises(PermissionError):
            scoped.search("notes/")


class TestScopedOps:
    def test_ops_denies_write(self, cap):
        scoped = cap.scope(ops={"read", "search"})
        with pytest.raises(PermissionError):
            scoped.write("any/key", "data")

    def test_ops_allows_read(self, cap):
        patcher, _ = _mock_file_store()
        try:
            scoped = cap.scope(ops={"read", "search"})
            result = scoped.read("any/key")
            assert isinstance(result, FileError)
        finally:
            patcher.stop()

    def test_ops_denies_read(self, cap):
        scoped = cap.scope(ops={"write"})
        with pytest.raises(PermissionError):
            scoped.read("any/key")

    def test_ops_denies_search(self, cap):
        scoped = cap.scope(ops={"read"})
        with pytest.raises(PermissionError):
            scoped.search("prefix/")


class TestNarrowPrefix:
    def test_narrow_prefix_allows_subdirectory(self, cap):
        scoped = cap.scope(prefix="config/")
        narrower = scoped.scope(prefix="config/db/")
        assert narrower._scope["prefix"] == "config/db/"

    def test_narrow_prefix_rejects_widening(self, cap):
        scoped = cap.scope(prefix="config/db/")
        with pytest.raises(ValueError):
            scoped.scope(prefix="config/")

    def test_narrow_prefix_rejects_different_path(self, cap):
        scoped = cap.scope(prefix="config/")
        with pytest.raises(ValueError):
            scoped.scope(prefix="notes/")


class TestNarrowOps:
    def test_narrow_ops_intersects(self, cap):
        scoped = cap.scope(ops={"read", "write", "search"})
        narrower = scoped.scope(ops={"read", "search"})
        assert narrower._scope["ops"] == {"read", "search"}

    def test_narrow_ops_successive(self, cap):
        s1 = cap.scope(ops={"read", "write", "search"})
        s2 = s1.scope(ops={"read", "write"})
        s3 = s2.scope(ops={"read"})
        assert s3._scope["ops"] == {"read"}

    def test_narrow_ops_empty_intersection(self, cap):
        scoped = cap.scope(ops={"read"})
        narrower = scoped.scope(ops={"write"})
        assert narrower._scope["ops"] == set()


class TestAllOps:
    def test_all_ops_class_attribute(self):
        assert FilesCapability.ALL_OPS == {"read", "write", "search"}

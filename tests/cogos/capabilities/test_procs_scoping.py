"""Tests for ProcsCapability scoping: _narrow(), _check(), list/get/spawn guards."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.procs import ProcsCapability


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.list_processes.return_value = []
    mock.get_process.return_value = None
    mock.get_process_by_name.return_value = None
    mock.upsert_process.return_value = uuid4()
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestUnscopedAllowsAll:
    def test_unscoped_allows_list(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        cap.list()  # should not raise

    def test_unscoped_allows_get(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        cap.get(name="worker")  # should not raise

    def test_unscoped_allows_spawn(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        cap.spawn(name="child", content="do something")  # should not raise


class TestScopedAllowsPermitted:
    def test_scoped_allows_list_when_permitted(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["list", "get"])
        cap.list()  # should not raise

    def test_scoped_allows_get_when_permitted(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["list", "get"])
        cap.get(name="worker")  # should not raise

    def test_scoped_allows_spawn_when_permitted(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["spawn"])
        cap.spawn(name="child", content="do something")  # should not raise


class TestScopedDenies:
    def test_scoped_denies_spawn_when_not_in_ops(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["list", "get"])
        with pytest.raises(PermissionError):
            cap.spawn(name="child", content="do something")

    def test_scoped_denies_list_when_not_in_ops(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["spawn"])
        with pytest.raises(PermissionError):
            cap.list()

    def test_scoped_denies_get_when_not_in_ops(self, repo, pid):
        cap = ProcsCapability(repo, pid).scope(ops=["spawn"])
        with pytest.raises(PermissionError):
            cap.get(name="worker")


class TestNarrow:
    def test_narrow_intersects_ops(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        s1 = cap.scope(ops=["list", "get", "spawn"])
        s2 = s1.scope(ops=["list", "spawn"])
        assert set(s2._scope["ops"]) == {"list", "spawn"}

    def test_narrow_intersects_disjoint(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        s1 = cap.scope(ops=["list"])
        s2 = s1.scope(ops=["spawn"])
        assert s2._scope["ops"] == []

    def test_narrow_unscoped_then_scoped(self, repo, pid):
        cap = ProcsCapability(repo, pid)
        s1 = cap.scope(ops=["list", "get"])
        assert set(s1._scope["ops"]) == {"get", "list"}

    def test_narrow_scoped_then_all(self, repo, pid):
        """Scoping with all ops after narrowing keeps the intersection."""
        cap = ProcsCapability(repo, pid)
        s1 = cap.scope(ops=["list"])
        s2 = s1.scope(ops=["list", "get", "spawn"])
        assert s2._scope["ops"] == ["list"]

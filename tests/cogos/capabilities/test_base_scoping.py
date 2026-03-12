"""Tests for Capability base-class scoping: scope(), _narrow(), _check()."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.base import Capability


class DummyCapability(Capability):
    """A test capability with ops-based scoping."""

    def _narrow(self, existing: dict, requested: dict) -> dict:
        """Intersect the 'ops' set if both sides specify it."""
        merged = {**existing, **requested}
        if "ops" in existing and "ops" in requested:
            merged["ops"] = existing["ops"] & requested["ops"]
        return merged

    def _check(self, op: str, **context: object) -> None:
        """Raise PermissionError if the scope restricts ops and op is not in the set."""
        allowed = self._scope.get("ops")
        if allowed is not None and op not in allowed:
            raise PermissionError(f"Operation '{op}' not permitted")


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScopeDefaults:
    def test_unscoped_has_empty_scope(self, repo, pid):
        cap = DummyCapability(repo, pid)
        assert cap._scope == {}

    def test_base_capability_has_empty_scope(self, repo, pid):
        cap = Capability(repo, pid)
        assert cap._scope == {}


class TestScopeCloning:
    def test_scope_returns_new_instance(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read", "write"})
        assert scoped is not cap

    def test_scope_does_not_mutate_original(self, repo, pid):
        cap = DummyCapability(repo, pid)
        cap.scope(ops={"read"})
        assert cap._scope == {}

    def test_scope_preserves_repo(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read"})
        assert scoped.repo is repo

    def test_scope_preserves_process_id(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read"})
        assert scoped.process_id == pid


class TestNarrow:
    def test_narrow_intersects_ops(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read", "write", "delete"})
        narrower = scoped.scope(ops={"read", "delete"})
        assert narrower._scope["ops"] == {"read", "delete"}

    def test_narrow_successive_narrows(self, repo, pid):
        cap = DummyCapability(repo, pid)
        s1 = cap.scope(ops={"read", "write", "delete"})
        s2 = s1.scope(ops={"read", "write"})
        s3 = s2.scope(ops={"read"})
        assert s3._scope["ops"] == {"read"}

    def test_base_narrow_merges(self, repo, pid):
        """Base Capability._narrow simply merges dicts."""
        cap = Capability(repo, pid)
        result = cap._narrow({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_base_narrow_overrides(self, repo, pid):
        cap = Capability(repo, pid)
        result = cap._narrow({"a": 1}, {"a": 99})
        assert result == {"a": 99}


class TestCheck:
    def test_check_allows_permitted_op(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read", "write"})
        scoped._check("read")  # should not raise

    def test_check_raises_for_unpermitted_op(self, repo, pid):
        cap = DummyCapability(repo, pid)
        scoped = cap.scope(ops={"read"})
        with pytest.raises(PermissionError, match="delete"):
            scoped._check("delete")

    def test_unscoped_allows_everything(self, repo, pid):
        cap = DummyCapability(repo, pid)
        cap._check("anything")  # should not raise

    def test_base_check_is_noop(self, repo, pid):
        """Base Capability._check does nothing (no enforcement)."""
        cap = Capability(repo, pid)
        cap._check("anything")  # should not raise

"""Tests for spawn() delegation authorization — parent must hold capability to delegate."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.files import FilesCapability
from cogos.capabilities.procs import ProcessError, ProcsCapability


@pytest.fixture
def repo():
    mock = MagicMock()
    mock.upsert_process.return_value = uuid4()
    return mock


@pytest.fixture
def parent_pid():
    return uuid4()


def _make_cap_model(name="files"):
    m = MagicMock()
    m.id = uuid4()
    m.enabled = True
    m.name = name
    return m


def test_spawn_denied_when_parent_lacks_capability(repo, parent_pid):
    """Parent has no grants at all — delegating any capability should fail."""
    repo.list_process_capabilities.return_value = []

    files_cap_model = _make_cap_model("files")
    repo.get_capability_by_name.return_value = files_cap_model

    procs = ProcsCapability(repo, parent_pid)
    files = FilesCapability(repo, parent_pid)

    result = procs.spawn(
        name="child",
        content="work",
        capabilities={"workspace": files.scope(prefix="/workspace/")},
    )

    assert isinstance(result, ProcessError)
    assert "parent does not hold" in result.error


def test_spawn_allowed_when_parent_holds_capability(repo, parent_pid):
    """Parent holds unscoped grant — child gets the capability."""
    files_cap_model = _make_cap_model("files")
    repo.get_capability_by_name.return_value = files_cap_model

    # Parent has an unscoped grant for this capability
    parent_grant = MagicMock()
    parent_grant.capability = files_cap_model.id
    parent_grant.config = None
    repo.list_process_capabilities.return_value = [parent_grant]

    procs = ProcsCapability(repo, parent_pid)
    files = FilesCapability(repo, parent_pid)

    result = procs.spawn(
        name="child",
        content="work",
        capabilities={"workspace": files.scope(prefix="/workspace/")},
    )

    assert not isinstance(result, ProcessError)
    assert hasattr(result, "id")
    repo.create_process_capability.assert_called_once()


def test_spawn_denied_when_child_widens_scope(repo, parent_pid):
    """Parent has scoped grant, child tries unscoped — denied."""
    files_cap_model = _make_cap_model("files")
    repo.get_capability_by_name.return_value = files_cap_model

    parent_grant = MagicMock()
    parent_grant.capability = files_cap_model.id
    parent_grant.config = {"prefix": "/workspace/"}
    repo.list_process_capabilities.return_value = [parent_grant]

    procs = ProcsCapability(repo, parent_pid)
    _files = FilesCapability(repo, parent_pid)

    # Child passes unscoped capability (None value = unscoped)
    result = procs.spawn(
        name="child",
        content="work",
        capabilities={"files": None},
    )

    assert isinstance(result, ProcessError)
    assert "cannot widen" in result.error.lower() or "exceeds" in result.error.lower()


def test_spawn_allowed_when_child_narrows_scope(repo, parent_pid):
    """Parent has scoped grant, child narrows further — allowed."""
    files_cap_model = _make_cap_model("files")
    repo.get_capability_by_name.return_value = files_cap_model

    parent_grant = MagicMock()
    parent_grant.capability = files_cap_model.id
    parent_grant.config = {"prefix": "/workspace/"}
    repo.list_process_capabilities.return_value = [parent_grant]

    procs = ProcsCapability(repo, parent_pid)
    files = FilesCapability(repo, parent_pid)

    result = procs.spawn(
        name="child",
        content="work",
        capabilities={"workspace": files.scope(prefix="/workspace/subdir/")},
    )

    assert not isinstance(result, ProcessError)
    assert hasattr(result, "id")


def test_spawn_denied_when_child_scope_exceeds_parent(repo, parent_pid):
    """Parent has ops=["read"], child tries ops=["read","write"] — denied."""
    files_cap_model = _make_cap_model("files")
    repo.get_capability_by_name.return_value = files_cap_model

    parent_grant = MagicMock()
    parent_grant.capability = files_cap_model.id
    parent_grant.config = {"ops": {"read"}}
    repo.list_process_capabilities.return_value = [parent_grant]

    procs = ProcsCapability(repo, parent_pid)
    files = FilesCapability(repo, parent_pid)

    result = procs.spawn(
        name="child",
        content="work",
        capabilities={"workspace": files.scope(ops={"read", "write"})},
    )

    assert isinstance(result, ProcessError)
    assert "exceeds" in result.error.lower()

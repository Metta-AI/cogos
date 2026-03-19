"""Tests for SchemasCapability."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.schemas import SchemaError, SchemasCapability
from cogos.db.models import Schema


@pytest.fixture
def repo():
    mock = MagicMock()
    return mock


@pytest.fixture
def pid():
    return uuid4()


class TestSchemaGet:
    def test_get_existing(self, repo, pid):
        s = Schema(name="metrics", definition={"fields": {"value": "number"}})
        repo.get_schema_by_name.return_value = s
        cap = SchemasCapability(repo, pid)
        result = cap.get("metrics")
        assert not isinstance(result, SchemaError)
        assert result.name == "metrics"
        assert result.definition == {"fields": {"value": "number"}}

    def test_get_missing(self, repo, pid):
        repo.get_schema_by_name.return_value = None
        cap = SchemasCapability(repo, pid)
        result = cap.get("nonexistent")
        assert hasattr(result, "error")


class TestSchemaList:
    def test_list(self, repo, pid):
        repo.list_schemas.return_value = [
            Schema(name="a", definition={}),
            Schema(name="b", definition={}),
        ]
        cap = SchemasCapability(repo, pid)
        result = cap.list()
        assert len(result) == 2


class TestSchemaScoping:
    def test_scoped_allows_matching(self, repo, pid):
        s = Schema(name="metrics", definition={})
        repo.get_schema_by_name.return_value = s
        cap = SchemasCapability(repo, pid).scope(names=["metrics*"])
        cap.get("metrics")  # should not raise

    def test_scoped_denies_non_matching(self, repo, pid):
        cap = SchemasCapability(repo, pid).scope(names=["metrics*"])
        with pytest.raises(PermissionError):
            cap.get("secrets")

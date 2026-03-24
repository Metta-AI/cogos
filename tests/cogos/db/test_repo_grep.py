"""Tests for repo grep_files query."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.db.repository import RdsDataApiRepository


@pytest.fixture
def repo():
    """Create a Repository with mocked RDS client."""
    with patch.object(RdsDataApiRepository, "__init__", lambda self: None):
        r = RdsDataApiRepository.__new__(RdsDataApiRepository)
        r._client = MagicMock()
        r._resource_arn = "arn:test"
        r._secret_arn = "arn:secret"
        r._database = "testdb"
        return r


class TestGrepFiles:
    def test_grep_returns_matching_keys_and_content(self, repo):
        repo._client.execute_statement.return_value = {
            "columnMetadata": [
                {"name": "key"},
                {"name": "content"},
            ],
            "records": [
                [
                    {"stringValue": "src/main.py"},
                    {"stringValue": "line1\nTODO fix this\nline3"},
                ],
            ],
        }
        results = repo.grep_files("TODO", prefix="src/", limit=100)
        assert len(results) == 1
        assert results[0][0] == "src/main.py"
        assert "TODO" in results[0][1]

    def test_grep_no_matches(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        results = repo.grep_files("nonexistent")
        assert results == []

    def test_grep_with_prefix(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        repo.grep_files("pattern", prefix="myprefix/")
        assert repo._client.execute_statement.called

"""Tests for repo glob_files query."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cogos.db.repository import Repository


@pytest.fixture
def repo():
    """Create a Repository with mocked RDS client."""
    with patch.object(Repository, "__init__", lambda self: None):
        r = Repository.__new__(Repository)
        r._client = MagicMock()
        r._resource_arn = "arn:test"
        r._secret_arn = "arn:secret"
        r._database = "testdb"
        return r


class TestGlobFiles:
    def test_glob_returns_matching_keys(self, repo):
        repo._client.execute_statement.return_value = {
            "columnMetadata": [{"name": "key"}],
            "records": [[{"stringValue": "src/config.yaml"}]],
        }
        results = repo.glob_files("src/*.yaml")
        assert results == ["src/config.yaml"]

    def test_glob_no_matches(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        results = repo.glob_files("nonexistent/**")
        assert results == []


class TestGlobToRegex:
    def test_star(self):
        assert Repository._glob_to_regex("src/*.py") == "^src/[^/]*\\.py$"

    def test_double_star(self):
        assert Repository._glob_to_regex("src/**/*.py") == "^src/.*[^/]*\\.py$"

    def test_question_mark(self):
        assert Repository._glob_to_regex("file?.txt") == "^file[^/]\\.txt$"

    def test_plain(self):
        assert Repository._glob_to_regex("exact/path.md") == "^exact/path\\.md$"

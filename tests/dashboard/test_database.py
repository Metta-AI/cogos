"""Tests for the dashboard db module."""

from unittest.mock import MagicMock, patch

import dashboard.db as db_mod
from dashboard.db import NullRepository, get_repo


def test_get_repo_returns_repository():
    """get_repo creates a Repository via create()."""
    db_mod._repo = None  # reset singleton
    mock_repo = MagicMock()
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.return_value = mock_repo
        result = get_repo()
        assert result is mock_repo
        MockRepo.create.assert_called_once()
    db_mod._repo = None  # cleanup


def test_get_repo_falls_back_to_null():
    """get_repo returns NullRepository when credentials are missing."""
    db_mod._repo = None
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.side_effect = ValueError("Missing credentials")
        result = get_repo()
        assert isinstance(result, NullRepository)
    db_mod._repo = None


def test_null_repository_returns_empty():
    """NullRepository returns empty results for all methods."""
    repo = NullRepository()
    assert repo.query("SELECT 1") == []
    assert repo.query_one("SELECT 1") is None
    assert repo.execute("UPDATE foo SET bar = 1") == 0

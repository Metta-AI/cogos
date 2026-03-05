"""Tests for the dashboard db module."""

from unittest.mock import MagicMock, patch

from dashboard.db import get_repo


def test_get_repo_returns_repository():
    """get_repo creates a Repository via create()."""
    import dashboard.db as db_mod

    db_mod._repo = None  # reset singleton
    mock_repo = MagicMock()
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.return_value = mock_repo
        result = get_repo()
        assert result is mock_repo
        MockRepo.create.assert_called_once()
    db_mod._repo = None  # cleanup

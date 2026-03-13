"""Tests for the dashboard db module."""

from unittest.mock import MagicMock, patch

import pytest

import dashboard.db as db_mod


def test_get_repo_returns_repository():
    """get_repo creates a Repository via create()."""
    db_mod._repo = None  # reset singleton
    mock_repo = MagicMock()
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.return_value = mock_repo
        result = db_mod.get_repo()
        assert result is mock_repo
        MockRepo.create.assert_called_once()
    db_mod._repo = None  # cleanup


def test_get_repo_raises_on_missing_credentials():
    """get_repo raises when credentials are missing."""
    db_mod._repo = None
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.side_effect = ValueError("Missing credentials")
        with pytest.raises(ValueError, match="Missing credentials"):
            db_mod.get_repo()
    db_mod._repo = None

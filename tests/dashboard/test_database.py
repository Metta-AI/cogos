"""Tests for the dashboard db module."""

from unittest.mock import MagicMock, patch

import pytest

import dashboard.db as db_mod


@pytest.fixture(autouse=True)
def _reset_repo_singleton(monkeypatch):
    """Ensure the singleton is reset before and after each test."""
    monkeypatch.setattr(db_mod, "_repo", None)
    monkeypatch.delenv("USE_LOCAL_DB", raising=False)


def test_get_repo_returns_repository():
    """get_repo creates a Repository via create()."""
    mock_repo = MagicMock()
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.return_value = mock_repo
        result = db_mod.get_repo()
        assert result is mock_repo
        MockRepo.create.assert_called_once()


def test_get_repo_raises_on_missing_credentials():
    """get_repo raises when credentials are missing."""
    with patch("dashboard.db.Repository") as MockRepo:
        MockRepo.create.side_effect = ValueError("Missing credentials")
        with pytest.raises(ValueError, match="Missing credentials"):
            db_mod.get_repo()

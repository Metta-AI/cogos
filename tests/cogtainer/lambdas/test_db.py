"""Tests for cogtainer.lambdas.shared.db.get_repo using region param."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_get_repo_passes_region_to_repository_create(monkeypatch):
    """get_repo should pass config.region to AwsCogtainerRepository.create."""
    # Reset the cached singleton
    import cogtainer.lambdas.shared.db as db_mod
    db_mod._repo = None

    monkeypatch.setenv("COGENT", "test")
    monkeypatch.setenv("DB_CLUSTER_ARN", "arn:rds:cluster")
    monkeypatch.setenv("DB_SECRET_ARN", "arn:secret:secret")
    monkeypatch.setenv("DB_NAME", "cogent_test")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    # Reset config singleton too
    import cogtainer.lambdas.shared.config as cfg_mod
    cfg_mod._config = None

    mock_repo = MagicMock()
    with patch("cogtainer.lambdas.shared.db.AwsCogtainerRepository") as MockRepo:
        MockRepo.create.return_value = mock_repo
        result = db_mod.get_repo()

    MockRepo.create.assert_called_once_with(
        resource_arn="arn:rds:cluster",
        secret_arn="arn:secret:secret",
        database="cogent_test",
        region="eu-west-1",
    )
    assert result is mock_repo

    # Clean up singletons
    db_mod._repo = None
    cfg_mod._config = None


def test_get_repo_no_boto3_import():
    """get_repo should not directly import boto3 (uses AwsCogtainerRepository.create with region)."""
    import inspect

    import cogtainer.lambdas.shared.db as db_mod

    source = inspect.getsource(db_mod)
    assert "boto3" not in source

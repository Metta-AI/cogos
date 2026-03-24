"""Singleton Data API AwsCogtainerRepository for Lambda handlers."""

from __future__ import annotations

from cogtainer.db.repository import AwsCogtainerRepository
from cogtainer.lambdas.shared.config import get_config

_repo: AwsCogtainerRepository | None = None


def get_repo() -> AwsCogtainerRepository:
    global _repo
    if _repo is None:
        config = get_config()
        _repo = AwsCogtainerRepository.create(
            resource_arn=config.db_cluster_arn,
            secret_arn=config.db_secret_arn,
            database=config.db_name,
            region=config.region,
        )
    return _repo

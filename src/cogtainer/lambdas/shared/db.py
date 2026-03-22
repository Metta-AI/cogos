"""Singleton Data API Repository for Lambda handlers."""

from __future__ import annotations

from cogtainer.db.repository import Repository
from cogtainer.lambdas.shared.config import get_config

_repo: Repository | None = None


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        config = get_config()
        _repo = Repository.create(
            resource_arn=config.db_cluster_arn,
            secret_arn=config.db_secret_arn,
            database=config.db_name,
            region=config.region,
        )
    return _repo

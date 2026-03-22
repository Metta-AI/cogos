"""Singleton Data API Repository for Lambda handlers."""

from __future__ import annotations

import boto3

from cogtainer.db.repository import Repository
from cogtainer.lambdas.shared.config import get_config

_repo: Repository | None = None


def get_repo() -> Repository:
    """Return cached Repository singleton using Data API."""
    global _repo
    if _repo is None:
        config = get_config()
        client = boto3.client("rds-data", region_name=config.region)
        _repo = Repository.create(
            resource_arn=config.db_cluster_arn,
            secret_arn=config.db_secret_arn,
            database=config.db_name,
            client=client,
        )
    return _repo

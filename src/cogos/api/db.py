"""Singleton Repository for the CogOS API service.

Requires DB_RESOURCE_ARN (or DB_CLUSTER_ARN), DB_SECRET_ARN, and DB_NAME env vars
for RDS Data API. Set USE_LOCAL_DB=1 to use LocalRepository for local dev; the
CLI defaults that store to the current checkout's `.local/cogos/` directory
unless COGOS_LOCAL_DATA overrides it.
"""

from __future__ import annotations

import functools
import logging
import os

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_repo() -> Repository:
    if os.environ.get("USE_LOCAL_DB") == "1":
        from cogos.db.local_repository import LocalRepository

        logger.info("USE_LOCAL_DB=1, using local repository")
        return LocalRepository()

    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("rds-data", region_name=region)
    return Repository.create(client=client)

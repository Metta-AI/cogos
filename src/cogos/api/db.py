"""Singleton Repository for the CogOS API service.

Requires DB_RESOURCE_ARN (or DB_CLUSTER_ARN), DB_SECRET_ARN, and DB_NAME env vars
for RDS Data API. Set USE_LOCAL_DB=1 to use LocalRepository for local dev; the
runtime resolves the correct data directory from the cogtainer config.
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
        try:
            from cogtainer.config import load_config, resolve_cogent_name, resolve_cogtainer_name
            from cogtainer.cogtainer_cli import _config_path
            from cogtainer.runtime.factory import create_runtime

            cfg = load_config(_config_path())
            ct_name = resolve_cogtainer_name(cfg)
            entry = cfg.cogtainers[ct_name]
            runtime = create_runtime(entry, cogtainer_name=ct_name)
            cogent_name = resolve_cogent_name(runtime.list_cogents())
            logger.info("USE_LOCAL_DB=1, using runtime repository for %s/%s", ct_name, cogent_name)
            return runtime.get_repository(cogent_name)
        except Exception:
            from cogos.db.local_repository import LocalRepository

            logger.info("USE_LOCAL_DB=1, falling back to default local repository")
            return LocalRepository()

    import boto3
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("rds-data", region_name=region)
    return Repository.create(client=client)

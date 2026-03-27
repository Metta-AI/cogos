"""Singleton Repository for the CogOS API service.

Requires DB_RESOURCE_ARN (or DB_CLUSTER_ARN), DB_SECRET_ARN, and DB_NAME env vars
for RDS Data API. Set USE_LOCAL_DB=1 to use SqliteRepository for local dev; the
runtime resolves the correct data directory from the cogtainer config.
"""

from __future__ import annotations

import functools
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_repo() -> Any:
    if os.environ.get("USE_LOCAL_DB") == "1":
        try:
            from cogtainer.config import load_config, resolve_cogent_name, resolve_cogtainer_name
            from cogtainer.runtime.factory import create_runtime

            cfg = load_config()
            ct_name = resolve_cogtainer_name(cfg)
            entry = cfg.cogtainers[ct_name]
            runtime = create_runtime(entry, cogtainer_name=ct_name)
            cogent_name = resolve_cogent_name(runtime.list_cogents())
            logger.info("USE_LOCAL_DB=1, using runtime repository for %s/%s", ct_name, cogent_name)
            return runtime.get_repository(cogent_name)
        except Exception:
            from cogtainer.config import local_data_dir
            from cogos.db.sqlite_repository import SqliteBackend
            from cogos.db.unified_repository import UnifiedRepository

            data_dir = str(local_data_dir())
            logger.info("USE_LOCAL_DB=1, falling back to default local repository at %s", data_dir)
            return UnifiedRepository(SqliteBackend(data_dir))

    import boto3

    from cogos.db.repository import RdsBackend
    from cogos.db.unified_repository import UnifiedRepository
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("rds-data", region_name=region)
    backend = RdsBackend.create(client=client)
    return UnifiedRepository(backend)

"""Singleton Repository for dashboard handlers.

Requires DB_RESOURCE_ARN (or DB_CLUSTER_ARN), DB_SECRET_ARN, and DB_NAME env vars
for RDS Data API. Set USE_LOCAL_DB=1 to use LocalRepository for local dev; the
CLI defaults that store to the current checkout's `.local/cogos/` directory
unless COGOS_LOCAL_DATA overrides it.
"""

from __future__ import annotations

import logging
import os

from cogos.db.local_repository import LocalRepository
from cogos.db.repository import Repository
from cogtainer.runtime.factory import create_executor_runtime

logger = logging.getLogger(__name__)

_repo: Repository | None = None


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        if os.environ.get("USE_LOCAL_DB") == "1":
            logger.info("USE_LOCAL_DB=1, using local repository")
            _repo = LocalRepository()
        else:
            runtime = create_executor_runtime()
            client = runtime.get_rds_data_client()
            _repo = Repository.create(client=client)
    assert _repo is not None
    return _repo

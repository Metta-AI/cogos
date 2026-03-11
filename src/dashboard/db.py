"""Singleton Repository for dashboard handlers.

Requires DB_RESOURCE_ARN, DB_SECRET_ARN, and DB_NAME env vars for RDS Data API.
Set USE_LOCAL_DB=1 to use LocalRepository (JSON file persistence) for local dev.
"""

from __future__ import annotations

import logging
import os

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)

_repo: Repository | None = None


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        if os.environ.get("USE_LOCAL_DB") == "1":
            from cogos.db.local_repository import LocalRepository
            logger.info("USE_LOCAL_DB=1, using local repository")
            _repo = LocalRepository()
        else:
            _repo = Repository.create()
    return _repo

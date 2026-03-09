"""Singleton Repository for dashboard handlers.

Requires DB_RESOURCE_ARN, DB_SECRET_ARN, and DB_NAME env vars for RDS Data API.
Set USE_LOCAL_DB=1 to use LocalRepository (JSON file persistence) for local dev.
"""

from __future__ import annotations

import logging
import os

from brain.db.repository import Repository
from cogos.db.repository import Repository as CogosRepository

logger = logging.getLogger(__name__)

_repo: Repository | None = None
_cogos_repo: CogosRepository | None = None


def get_cogos_repo() -> CogosRepository:
    global _cogos_repo
    if _cogos_repo is None:
        if os.environ.get("USE_LOCAL_DB") == "1":
            from cogos.db.local_repository import LocalRepository as CogosLocalRepository
            logger.info("USE_LOCAL_DB=1, using local cogos repository")
            _cogos_repo = CogosLocalRepository()
        else:
            _cogos_repo = CogosRepository.create()
    return _cogos_repo


def get_repo() -> Repository:
    """Return cached Repository singleton (reads env vars on first call).

    Requires DB_RESOURCE_ARN, DB_SECRET_ARN, and DB_NAME environment variables.
    Set USE_LOCAL_DB=1 to use LocalRepository instead (local dev only).
    """
    global _repo
    if _repo is None:
        if os.environ.get("USE_LOCAL_DB") == "1":
            from brain.db.local_repository import LocalRepository
            logger.info("USE_LOCAL_DB=1, using local repository")
            _repo = LocalRepository()
        else:
            _repo = Repository.create()
            logger.info("Connected to database via Data API")
    return _repo

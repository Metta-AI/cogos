"""Singleton Repository for the CogOS API service."""

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
    assert _repo is not None
    return _repo

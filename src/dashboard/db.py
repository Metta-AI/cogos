"""Singleton Repository for dashboard handlers (uses RDS Data API).

Falls back to a NullRepository that returns empty results when Data API
credentials are not configured (DB_RESOURCE_ARN, DB_SECRET_ARN, DB_NAME).
"""

from __future__ import annotations

import logging
from typing import Any

from brain.db.repository import Repository

logger = logging.getLogger(__name__)

_repo: Repository | NullRepository | None = None


class NullRepository:
    """Returns empty results for all queries (used when DB is not configured)."""

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        return []

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict | None:
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        return 0


def get_repo() -> Repository | NullRepository:
    """Return cached Repository singleton (reads env vars on first call).

    If Data API credentials are not set, returns a NullRepository that
    yields empty results so the dashboard renders with no data instead
    of crashing.
    """
    global _repo
    if _repo is None:
        try:
            _repo = Repository.create()
            logger.info("Connected to database via Data API")
        except (ValueError, Exception) as exc:
            logger.warning("Database not configured, using empty data: %s", exc)
            _repo = NullRepository()
    return _repo

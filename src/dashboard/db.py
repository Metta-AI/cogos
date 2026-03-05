"""Singleton Repository for dashboard handlers (uses RDS Data API)."""

from __future__ import annotations

from brain.db.repository import Repository

_repo: Repository | None = None


def get_repo() -> Repository:
    """Return cached Repository singleton (reads env vars on first call)."""
    global _repo
    if _repo is None:
        _repo = Repository.create()
    return _repo

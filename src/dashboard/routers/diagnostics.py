from __future__ import annotations

import json
import logging

from fastapi import APIRouter

from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["diagnostics"])


def _read_file(key: str) -> str | None:
    store = FileStore(get_repo())
    return store.get_content(key)


@router.get("/diagnostics")
def get_diagnostics(name: str) -> dict:
    """Return latest diagnostic results from data/diagnostics/current.json."""
    content = _read_file("data/diagnostics/current.json")
    if content is None:
        return {"status": "no_data", "message": "No diagnostic results available"}
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"status": "error", "message": "Invalid diagnostic data"}


@router.get("/diagnostics/history")
def get_diagnostics_history(name: str, limit: int = 10) -> dict:
    """Return the last N diagnostic runs from file versions of current.json."""
    store = FileStore(get_repo())
    versions = store.history("data/diagnostics/current.json")
    if not versions:
        return {"runs": []}
    # Sort descending by version number (newest first), take last N
    versions.sort(key=lambda v: v.version, reverse=True)
    runs = []
    for v in versions[:limit]:
        try:
            data = json.loads(v.content)
            runs.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return {"runs": runs}


@router.get("/diagnostics/changelog")
def get_diagnostics_changelog(name: str) -> dict:
    """Return diagnostic changelog."""
    content = _read_file("data/diagnostics/changelog.md")
    return {"content": content or ""}


@router.get("/diagnostics/log")
def get_diagnostics_log(name: str) -> dict:
    """Return diagnostic run log."""
    content = _read_file("data/diagnostics/log.md")
    return {"content": content or ""}

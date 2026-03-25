from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from cogos.db.models import ChannelMessage
from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["diagnostics"])


def _read_file(key: str) -> str | None:
    store = FileStore(get_repo())
    return store.get_content(key)


_DIAG_KEY = "mnt/disk/diagnostics/current.json"


@router.get("/diagnostics")
def get_diagnostics(name: str) -> dict:
    """Return latest diagnostic results."""
    content = _read_file(_DIAG_KEY)
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
    versions = store.history(_DIAG_KEY)
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
    content = _read_file("mnt/disk/diagnostics/changelog.md")
    return {"content": content if content is not None else ""}


@router.get("/diagnostics/log")
def get_diagnostics_log(name: str) -> dict:
    """Return diagnostic run log."""
    content = _read_file("mnt/disk/diagnostics/log.md")
    return {"content": content if content is not None else ""}


@router.post("/diagnostics/run")
def rerun_diagnostics(name: str) -> dict:
    """Trigger a new diagnostic run by sending a message to system:diagnostics."""
    repo = get_repo()
    channels = repo.list_channels()
    diag_channel = next((ch for ch in channels if ch.name == "system:diagnostics"), None)
    if not diag_channel:
        raise HTTPException(status_code=404, detail="system:diagnostics channel not found")

    message = ChannelMessage(
        channel=diag_channel.id,
        sender_process=None,
        payload={"trigger": "dashboard", "source": "dashboard-rerun"},
    )
    message_id = repo.append_channel_message(message)
    return {"status": "triggered", "message_id": str(message_id)}

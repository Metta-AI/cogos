from __future__ import annotations

from fastapi import APIRouter, Query

from dashboard.db import get_repo
from dashboard.models import StatusResponse

router = APIRouter()

_RANGE_TO_INTERVAL = {
    "1m": "1 minute",
    "10m": "10 minutes",
    "1h": "1 hour",
    "24h": "24 hours",
    "1w": "7 days",
}


def _interval(range_str: str) -> str:
    return _RANGE_TO_INTERVAL.get(range_str, "1 hour")


@router.get("/status", response_model=StatusResponse)
def get_status(name: str, range: str = Query("1h", alias="range")):
    interval = _interval(range)
    repo = get_repo()
    row = repo.query_one(
        "SELECT "
        "(SELECT count(*) FROM conversations WHERE cogent_id = :cid AND status = 'active') AS active_sessions, "
        "(SELECT count(*) FROM conversations WHERE cogent_id = :cid) AS total_conversations, "
        "(SELECT count(*) FROM triggers WHERE cogent_id = :cid AND enabled = true) AS trigger_count, "
        "(SELECT count(*) FROM alerts WHERE cogent_id = :cid AND resolved_at IS NULL) AS unresolved_alerts, "
        "(SELECT count(*) FROM events WHERE cogent_id = :cid"
        f" AND created_at > now() - interval '{interval}') AS recent_events",
        {"cid": name},
    )
    return StatusResponse(cogent_id=name, **(row or {}))

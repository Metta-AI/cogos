from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from dashboard.db import get_repo
from dashboard.models import Event, EventsResponse, EventTreeResponse

router = APIRouter(tags=["events"])

_RANGE_TO_INTERVAL = {
    "1m": "1 minute",
    "10m": "10 minutes",
    "1h": "1 hour",
    "24h": "24 hours",
    "1w": "7 days",
}


def _interval(range_key: str) -> str:
    return _RANGE_TO_INTERVAL.get(range_key, "1 hour")


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


@router.get("/events", response_model=EventsResponse)
def list_events(
    name: str,
    range: str = Query("1h", alias="range"),
    type: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=1000),
) -> EventsResponse:
    repo = get_repo()
    interval = _interval(range)

    if type:
        rows = repo.query(
            "SELECT id, event_type, source, payload, parent_event_id, created_at "
            "FROM events "
            "WHERE cogent_id = :cid AND created_at > now() - interval '"
            + interval
            + "' AND event_type LIKE :etype "
            "ORDER BY created_at DESC LIMIT :lim",
            {"cid": name, "etype": f"%{type}%", "lim": limit},
        )
    else:
        rows = repo.query(
            "SELECT id, event_type, source, payload, parent_event_id, created_at "
            "FROM events "
            "WHERE cogent_id = :cid AND created_at > now() - interval '"
            + interval
            + "' ORDER BY created_at DESC LIMIT :lim",
            {"cid": name, "lim": limit},
        )

    events = [
        Event(
            id=r["id"],
            event_type=r.get("event_type"),
            source=r.get("source"),
            payload=_try_parse_json(r.get("payload")),
            parent_event_id=r.get("parent_event_id"),
            created_at=str(r["created_at"]) if r.get("created_at") else None,
        )
        for r in rows
    ]
    return EventsResponse(cogent_id=name, count=len(events), events=events)


@router.get("/events/{event_id}/tree", response_model=EventTreeResponse)
def event_tree(name: str, event_id: int) -> EventTreeResponse:
    repo = get_repo()

    # Walk up to root
    root_row = repo.query_one(
        """
        WITH RECURSIVE ancestors AS (
          SELECT id, parent_event_id FROM events WHERE id = :eid
          UNION ALL
          SELECT e.id, e.parent_event_id FROM events e JOIN ancestors a ON e.id = a.parent_event_id
        ) SELECT id FROM ancestors WHERE parent_event_id IS NULL
        """,
        {"eid": event_id},
    )
    if not root_row:
        return EventTreeResponse(root_event_id=None, count=0, events=[])

    root_id = root_row["id"]

    # Get full tree from root
    rows = repo.query(
        """
        WITH RECURSIVE tree AS (
          SELECT id, cogent_id, event_type, source, payload, parent_event_id, created_at
          FROM events WHERE id = :rid
          UNION ALL
          SELECT e.id, e.cogent_id, e.event_type, e.source, e.payload, e.parent_event_id, e.created_at
          FROM events e JOIN tree t ON e.parent_event_id = t.id
        ) SELECT * FROM tree ORDER BY created_at
        """,
        {"rid": root_id},
    )

    events = [
        Event(
            id=r["id"],
            event_type=r.get("event_type"),
            source=r.get("source"),
            payload=_try_parse_json(r.get("payload")),
            parent_event_id=r.get("parent_event_id"),
            created_at=str(r["created_at"]) if r.get("created_at") else None,
        )
        for r in rows
    ]
    return EventTreeResponse(root_event_id=root_id, count=len(events), events=events)

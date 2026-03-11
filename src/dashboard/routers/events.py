from __future__ import annotations

from fastapi import APIRouter, Query

from dashboard.db import get_repo
from dashboard.models import Event, EventsResponse, EventTreeResponse

router = APIRouter(tags=["events"])


def _event_to_model(e) -> Event:
    return Event(
        id=str(e.id),
        event_type=e.event_type,
        source=e.source,
        payload=e.payload,
        parent_event_id=str(e.parent_event) if e.parent_event else None,
        created_at=str(e.created_at) if e.created_at else None,
    )


@router.get("/events", response_model=EventsResponse)
def list_events(
    name: str,
    range: str = Query("1h", alias="range"),
    type: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=1000),
) -> EventsResponse:
    repo = get_repo()
    db_events = repo.get_events(event_type=type, limit=limit)
    events = [_event_to_model(e) for e in db_events]
    return EventsResponse(cogent_name=name, count=len(events), events=events)


@router.get("/events/{event_id}/tree", response_model=EventTreeResponse)
def event_tree(name: str, event_id: str) -> EventTreeResponse:
    repo = get_repo()
    # Fetch all events and find the tree containing this event
    all_events = repo.get_events(limit=1000)
    by_id = {str(e.id): e for e in all_events}
    target = by_id.get(event_id)
    if not target:
        return EventTreeResponse(root_event_id=None, count=0, events=[])

    # Walk up to root
    root = target
    visited = {str(root.id)}
    while root.parent_event and str(root.parent_event) in by_id:
        pid = str(root.parent_event)
        if pid in visited:
            break
        visited.add(pid)
        root = by_id[pid]

    # Collect all descendants from root
    def collect(eid: str) -> list:
        result = [by_id[eid]]
        for e in all_events:
            if str(e.parent_event) == eid if e.parent_event else False:
                result.extend(collect(str(e.id)))
        return result

    tree_events = collect(str(root.id))
    events = [_event_to_model(e) for e in tree_events]
    return EventTreeResponse(root_event_id=str(root.id), count=len(events), events=events)

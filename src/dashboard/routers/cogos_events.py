from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Event, EventDelivery
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-events"])


# ── Response models ─────────────────────────────────────────────────


class EventOut(BaseModel):
    id: str
    event_type: str
    source: str | None = None
    payload: dict
    parent_event: str | None = None
    created_at: str | None = None


class DeliveryOut(BaseModel):
    id: str
    event: str
    handler: str
    status: str
    run: str | None = None
    created_at: str | None = None


class EventDetail(BaseModel):
    event: EventOut
    deliveries: list[DeliveryOut]


class EventsResponse(BaseModel):
    count: int
    events: list[EventOut]


# ── Helpers ─────────────────────────────────────────────────────────


def _event_out(e: Event) -> EventOut:
    return EventOut(
        id=str(e.id),
        event_type=e.event_type,
        source=e.source,
        payload=e.payload,
        parent_event=str(e.parent_event) if e.parent_event else None,
        created_at=str(e.created_at) if e.created_at else None,
    )


def _delivery_out(d: EventDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=str(d.id),
        event=str(d.event),
        handler=str(d.handler),
        status=d.status.value,
        run=str(d.run) if d.run else None,
        created_at=str(d.created_at) if d.created_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/cogos-events", response_model=EventsResponse)
def list_events(
    name: str,
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(100, ge=1, le=1000),
) -> EventsResponse:
    repo = get_repo()
    items = repo.get_events(event_type=event_type, limit=limit)
    out = [_event_out(e) for e in items]
    return EventsResponse(count=len(out), events=out)


@router.get("/cogos-events/{event_id}", response_model=EventDetail)
def get_event(name: str, event_id: str) -> EventDetail:
    repo = get_repo()
    # Fetch the specific event by querying for it
    rows = repo.query(
        "SELECT * FROM cogos_event WHERE id = :id",
        {"id": UUID(event_id)},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Event not found")
    row = rows[0]
    event = Event(
        id=UUID(row["id"]),
        event_type=row["event_type"],
        source=row.get("source"),
        payload=repo._json_field(row, "payload", {}),
        parent_event=UUID(row["parent_event"]) if row.get("parent_event") else None,
        created_at=repo._ts(row, "created_at"),
    )

    # Fetch deliveries for this event
    delivery_rows = repo.query(
        "SELECT * FROM cogos_event_delivery WHERE event = :event ORDER BY created_at",
        {"event": UUID(event_id)},
    )
    deliveries = [
        EventDelivery(
            id=UUID(r["id"]),
            event=UUID(r["event"]),
            handler=UUID(r["handler"]),
            status=r["status"],
            run=UUID(r["run"]) if r.get("run") else None,
            created_at=repo._ts(r, "created_at"),
        )
        for r in delivery_rows
    ]

    return EventDetail(
        event=_event_out(event),
        deliveries=[_delivery_out(d) for d in deliveries],
    )

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cogos.db.models import EventType
from dashboard.db import get_repo

router = APIRouter(tags=["event-types"])


class EventTypeOut(BaseModel):
    name: str
    description: str
    source: str
    created_at: str | None = None


class EventTypesResponse(BaseModel):
    count: int
    event_types: list[EventTypeOut]


class EventTypeCreate(BaseModel):
    name: str
    description: str = ""


def _to_out(et: EventType) -> EventTypeOut:
    return EventTypeOut(
        name=et.name,
        description=et.description,
        source=et.source,
        created_at=str(et.created_at) if et.created_at else None,
    )


@router.get("/event-types", response_model=EventTypesResponse)
def list_event_types(name: str) -> EventTypesResponse:
    repo = get_repo()
    items = repo.list_event_types()
    out = [_to_out(et) for et in items]
    return EventTypesResponse(count=len(out), event_types=out)


@router.post("/event-types", response_model=EventTypeOut)
def create_event_type(name: str, body: EventTypeCreate) -> EventTypeOut:
    repo = get_repo()
    et = EventType(name=body.name, description=body.description, source="manual")
    repo.upsert_event_type(et)
    return _to_out(et)


@router.delete("/event-types/{event_name:path}")
def delete_event_type(name: str, event_name: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_event_type(event_name)
    return {"deleted": deleted}

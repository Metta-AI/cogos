from __future__ import annotations

import fnmatch
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Handler
from dashboard.db import get_cogos_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-handlers"])


# ── Request / response models ──────────────────────────────────────


class HandlerOut(BaseModel):
    id: str
    process: str
    process_name: str | None = None
    event_pattern: str
    enabled: bool
    fired_1m: int = 0
    fired_5m: int = 0
    fired_1h: int = 0
    fired_24h: int = 0
    created_at: str | None = None


class HandlerCreate(BaseModel):
    process: str  # process UUID
    event_pattern: str
    enabled: bool = True


class HandlersResponse(BaseModel):
    count: int
    handlers: list[HandlerOut]


# ── Helpers ─────────────────────────────────────────────────────────


def _to_out(
    h: Handler,
    process_names: dict[UUID, str],
    events_by_time: dict[str, list[datetime]],
) -> HandlerOut:
    now = datetime.now(timezone.utc)
    cutoffs = {
        "1m": now - timedelta(minutes=1),
        "5m": now - timedelta(minutes=5),
        "1h": now - timedelta(hours=1),
        "24h": now - timedelta(hours=24),
    }

    # Count events matching this handler's pattern
    fired = {"1m": 0, "5m": 0, "1h": 0, "24h": 0}
    for etype, timestamps in events_by_time.items():
        if fnmatch.fnmatch(etype, h.event_pattern):
            for ts in timestamps:
                ts_aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                for key, cutoff in cutoffs.items():
                    if ts_aware >= cutoff:
                        fired[key] += 1

    return HandlerOut(
        id=str(h.id),
        process=str(h.process),
        process_name=process_names.get(h.process),
        event_pattern=h.event_pattern,
        enabled=h.enabled,
        fired_1m=fired["1m"],
        fired_5m=fired["5m"],
        fired_1h=fired["1h"],
        fired_24h=fired["24h"],
        created_at=str(h.created_at) if h.created_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/handlers", response_model=HandlersResponse)
def list_handlers(
    name: str,
    process: str | None = Query(None, description="Filter by process UUID"),
) -> HandlersResponse:
    repo = get_cogos_repo()
    pid = UUID(process) if process else None
    items = repo.list_handlers(process_id=pid)

    # Build process name lookup
    processes = repo.list_processes()
    process_names = {p.id: p.name for p in processes}

    # Build event timestamps grouped by event_type (last 24h)
    events = repo.get_events(limit=1000)
    events_by_time: dict[str, list[datetime]] = {}
    for e in events:
        if e.created_at:
            events_by_time.setdefault(e.event_type, []).append(e.created_at)

    out = [_to_out(h, process_names, events_by_time) for h in items]
    return HandlersResponse(count=len(out), handlers=out)


@router.post("/handlers", response_model=HandlerOut)
def create_handler(name: str, body: HandlerCreate) -> HandlerOut:
    repo = get_cogos_repo()
    h = Handler(
        process=UUID(body.process),
        event_pattern=body.event_pattern,
        enabled=body.enabled,
    )
    repo.create_handler(h)
    return _to_out(h)


@router.delete("/handlers/{handler_id}")
def delete_handler(name: str, handler_id: str) -> dict:
    repo = get_cogos_repo()
    if not repo.delete_handler(UUID(handler_id)):
        raise HTTPException(status_code=404, detail="Handler not found")
    return {"deleted": True, "id": handler_id}

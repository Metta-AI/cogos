from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from cogos.db.models import ProcessStatus
from dashboard.db import get_cogos_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-status"])


# ── Response models ─────────────────────────────────────────────────


class ProcessCounts(BaseModel):
    total: int
    by_status: dict[str, int]


class CogosStatusResponse(BaseModel):
    processes: ProcessCounts
    files: int
    capabilities: int
    recent_events: list[dict]
    recent_runs: list[dict]


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/cogos-status", response_model=CogosStatusResponse)
def cogos_status(name: str) -> CogosStatusResponse:
    repo = get_cogos_repo()

    # Process counts by status
    all_procs = repo.list_processes()
    counts: dict[str, int] = {}
    for p in all_procs:
        s = p.status.value
        counts[s] = counts.get(s, 0) + 1

    # File count
    files = repo.list_files()
    file_count = len(files)

    # Capability count
    caps = repo.list_capabilities()
    cap_count = len(caps)

    # Recent events (last 10)
    events = repo.get_events(limit=10)
    recent_events = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "source": e.source,
            "created_at": str(e.created_at) if e.created_at else None,
        }
        for e in events
    ]

    # Recent runs (last 10)
    runs = repo.list_runs(limit=10)
    recent_runs = [
        {
            "id": str(r.id),
            "process": str(r.process),
            "status": r.status.value,
            "duration_ms": r.duration_ms,
            "cost_usd": float(r.cost_usd),
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in runs
    ]

    return CogosStatusResponse(
        processes=ProcessCounts(total=len(all_procs), by_status=counts),
        files=file_count,
        capabilities=cap_count,
        recent_events=recent_events,
        recent_runs=recent_runs,
    )

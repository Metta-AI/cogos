from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from cogos.db.models import ProcessStatus
from dashboard.db import get_repo

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
    recent_events: int
    recent_runs: list[dict]
    scheduler_last_tick: str | None = None


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/cogos-status", response_model=CogosStatusResponse)
def cogos_status(name: str) -> CogosStatusResponse:
    repo = get_repo()

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

    # Recent events count
    events = repo.get_events(limit=100)
    recent_event_count = len(events)

    # Recent runs (last 10) with process name
    proc_map = {p.id: p.name for p in all_procs}
    runs = repo.list_runs(limit=10)
    recent_runs = [
        {
            "id": str(r.id),
            "process_name": proc_map.get(r.process, str(r.process)),
            "status": r.status.value,
            "duration_ms": r.duration_ms,
            "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in runs
    ]

    # Scheduler heartbeat
    scheduler_tick = None
    try:
        meta = repo.get_meta("scheduler:last_tick")
        if meta and meta["updated_at"]:
            ts = meta["updated_at"]
            if "+" not in ts and "Z" not in ts:
                ts += "+00:00"
            scheduler_tick = ts
    except Exception:
        pass

    return CogosStatusResponse(
        processes=ProcessCounts(total=len(all_procs), by_status=counts),
        files=file_count,
        capabilities=cap_count,
        recent_events=recent_event_count,
        recent_runs=recent_runs,
        scheduler_last_tick=scheduler_tick,
    )

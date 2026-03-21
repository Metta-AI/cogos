from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from cogos.db.models import ALL_EPOCHS
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-status"])


# ── Response models ─────────────────────────────────────────────────


class ProcessCounts(BaseModel):
    total: int
    by_status: dict[str, int]


class AgeInfo(BaseModel):
    image: str | None = None
    content: str | None = None
    stack: str | None = None
    schema: str | None = None
    state: str | None = None


class CogosStatusResponse(BaseModel):
    processes: ProcessCounts
    files: int
    capabilities: int
    recent_channels: int
    recent_runs: list[dict]
    scheduler_last_tick: str | None = None
    ages: AgeInfo = AgeInfo()
    reboot_epoch: int = 0


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/cogos-status", response_model=CogosStatusResponse)
def cogos_status(
    name: str,
    epoch: str | None = Query(None, description="Epoch filter"),
) -> CogosStatusResponse:
    repo = get_repo()
    ep = ALL_EPOCHS if epoch == "all" else None

    # Process counts by status
    all_procs = repo.list_processes(epoch=ep)
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

    # Channel count
    channels = repo.list_channels() if hasattr(repo, 'list_channels') else []
    channel_count = len(channels)

    # Recent runs (last 10) with process name
    proc_map = {p.id: p.name for p in all_procs}
    runs = repo.list_runs(limit=10, epoch=ep)
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

    # Scheduler heartbeat + ages from meta table
    scheduler_tick = None
    ages = AgeInfo()

    def _read_meta_ts(key: str) -> str | None:
        try:
            meta = repo.get_meta(key)
            if meta and meta["updated_at"]:
                ts = meta["updated_at"]
                if "+" not in ts and "Z" not in ts:
                    ts += "+00:00"
                return ts
        except Exception:
            pass
        return None

    scheduler_tick = _read_meta_ts("scheduler:last_tick")
    ages.image = _read_meta_ts("image:booted_at")
    ages.content = _read_meta_ts("content:deployed_at")
    ages.stack = _read_meta_ts("stack:updated_at")
    ages.schema = _read_meta_ts("schema:migrated_at")
    ages.state = _read_meta_ts("state:modified_at")

    return CogosStatusResponse(
        processes=ProcessCounts(total=len(all_procs), by_status=counts),
        files=file_count,
        capabilities=cap_count,
        recent_channels=channel_count,
        recent_runs=recent_runs,
        scheduler_last_tick=scheduler_tick,
        ages=ages,
        reboot_epoch=repo.reboot_epoch,
    )

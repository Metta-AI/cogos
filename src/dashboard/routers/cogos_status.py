from __future__ import annotations

import json as _json
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

    # Process counts by status — need full list for proc_map below
    all_procs = repo.list_processes(epoch=ep)
    counts: dict[str, int] = {}
    for p in all_procs:
        s = p.status.value
        counts[s] = counts.get(s, 0) + 1

    # Use COUNT queries to avoid fetching large payloads
    def _count(table: str) -> int:
        try:
            resp = repo._execute(f"SELECT COUNT(*) AS cnt FROM {table}")
            records = resp.get("records", [])
            if records and records[0]:
                return records[0][0].get("longValue", 0)
        except Exception:
            pass
        return 0

    file_count = _count("cogos_file")
    cap_count = _count("cogos_capability")
    channel_count = _count("cogos_channel")

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


class DashboardInitResponse(BaseModel):
    cogos_status: CogosStatusResponse
    processes: list[dict]
    alerts: list[dict]
    channels: list[dict] | None = None


@router.get("/dashboard-init")
def dashboard_init(
    name: str,
    epoch: str | None = Query(None, description="Epoch filter"),
) -> DashboardInitResponse:
    """Combined endpoint for initial dashboard load — returns cogos-status,
    processes, and alerts in a single request to avoid serialization delay."""
    repo = get_repo()
    ep = ALL_EPOCHS if epoch == "all" else None

    # --- cogos-status ---
    all_procs = repo.list_processes(epoch=ep)
    counts: dict[str, int] = {}
    for p in all_procs:
        s = p.status.value
        counts[s] = counts.get(s, 0) + 1

    def _count(table: str) -> int:
        try:
            resp = repo._execute(f"SELECT COUNT(*) AS cnt FROM {table}")
            records = resp.get("records", [])
            if records and records[0]:
                return records[0][0].get("longValue", 0)
        except Exception:
            pass
        return 0

    file_count = _count("cogos_file")
    cap_count = _count("cogos_capability")
    channel_count = _count("cogos_channel")

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

    cs = CogosStatusResponse(
        processes=ProcessCounts(total=len(all_procs), by_status=counts),
        files=file_count,
        capabilities=cap_count,
        recent_channels=channel_count,
        recent_runs=recent_runs,
        scheduler_last_tick=scheduler_tick,
        ages=ages,
        reboot_epoch=repo.reboot_epoch,
    )

    # --- processes (already fetched) ---
    process_list = [
        {
            "id": str(p.id),
            "name": p.name,
            "mode": p.mode.value,
            "executor": p.executor,
            "status": p.status.value,
            "priority": p.priority,
            "required_tags": p.required_tags,
            "model": p.model,
            "preemptible": p.preemptible,
            "parent_process": str(p.parent_process) if p.parent_process else None,
            "epoch": p.epoch,
            "updated_at": str(p.updated_at) if p.updated_at else None,
            "created_at": str(p.created_at) if p.created_at else None,
        }
        for p in all_procs
    ]

    # --- alerts ---
    alert_list: list[dict] = []
    try:
        alert_rows = repo.list_alerts(resolved=False, limit=50)
        for a in alert_rows:
            d = a if isinstance(a, dict) else (a.model_dump() if hasattr(a, "model_dump") else a.__dict__)
            meta = d.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except Exception:
                    pass
            alert_list.append({
                "id": str(d.get("id", "")),
                "severity": d.get("severity", ""),
                "alert_type": d.get("alert_type", ""),
                "source": d.get("source", ""),
                "message": d.get("message", ""),
                "metadata": meta,
                "resolved_at": str(d["resolved_at"]) if d.get("resolved_at") else None,
                "created_at": str(d["created_at"]) if d.get("created_at") else None,
            })
    except Exception:
        logger.warning("Failed to fetch alerts for dashboard-init", exc_info=True)

    # --- channels with recent messages (batch) ---
    channels_out: list[dict] = []
    try:
        from dashboard.routers.channels import (
            _batch_count_handlers,
            _batch_count_messages,
        )
        all_channels = repo.list_channels(limit=200)
        channel_ids = [ch.id for ch in all_channels]
        msg_counts = _batch_count_messages(repo, channel_ids)
        handler_counts = _batch_count_handlers(repo, channel_ids)

        for ch in all_channels:
            channels_out.append({
                "id": str(ch.id),
                "name": ch.name,
                "channel_type": ch.channel_type.value,
                "owner_process": str(ch.owner_process) if ch.owner_process else None,
                "owner_process_name": proc_map.get(ch.owner_process) if ch.owner_process else None,
                "message_count": msg_counts.get(ch.id, 0),
                "subscriber_count": handler_counts.get(ch.id, 0),
                "auto_close": ch.auto_close,
                "closed_at": str(ch.closed_at) if ch.closed_at else None,
                "created_at": str(ch.created_at) if ch.created_at else None,
            })
    except Exception:
        logger.warning("Failed to fetch channels for dashboard-init", exc_info=True)

    return DashboardInitResponse(
        cogos_status=cs,
        processes=process_list,
        alerts=alert_list,
        channels=channels_out or None,
    )

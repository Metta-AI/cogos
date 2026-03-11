from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Run
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-runs"])


# ── Response models ─────────────────────────────────────────────────


class RunSummary(BaseModel):
    id: str
    process: str
    process_name: str | None = None
    runner: str | None = None
    event: str | None = None
    conversation: str | None = None
    status: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int | None = None
    error: str | None = None
    model_version: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class RunDetail(BaseModel):
    id: str
    process: str
    event: str | None = None
    conversation: str | None = None
    status: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int | None = None
    error: str | None = None
    model_version: str | None = None
    result: dict | None = None
    scope_log: list[dict]
    created_at: str | None = None
    completed_at: str | None = None


class RunsResponse(BaseModel):
    count: int
    runs: list[RunSummary]


# ── Helpers ─────────────────────────────────────────────────────────


def _summary(
    r: Run,
    process_names: dict[UUID, str] | None = None,
    process_runners: dict[UUID, str] | None = None,
) -> RunSummary:
    return RunSummary(
        id=str(r.id),
        process=str(r.process),
        process_name=process_names.get(r.process) if process_names else None,
        runner=process_runners.get(r.process) if process_runners else None,
        event=str(r.event) if r.event else None,
        conversation=str(r.conversation) if r.conversation else None,
        status=r.status.value,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        cost_usd=float(r.cost_usd),
        duration_ms=r.duration_ms,
        error=r.error,
        model_version=r.model_version,
        created_at=str(r.created_at) if r.created_at else None,
        completed_at=str(r.completed_at) if r.completed_at else None,
    )


def _detail(r: Run) -> RunDetail:
    return RunDetail(
        id=str(r.id),
        process=str(r.process),
        event=str(r.event) if r.event else None,
        conversation=str(r.conversation) if r.conversation else None,
        status=r.status.value,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        cost_usd=float(r.cost_usd),
        duration_ms=r.duration_ms,
        error=r.error,
        model_version=r.model_version,
        result=r.result,
        scope_log=r.scope_log,
        created_at=str(r.created_at) if r.created_at else None,
        completed_at=str(r.completed_at) if r.completed_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/runs", response_model=RunsResponse)
def list_runs(
    name: str,
    process: str | None = Query(None, description="Filter by process UUID"),
    limit: int = Query(50, ge=1, le=500),
) -> RunsResponse:
    repo = get_repo()
    pid = UUID(process) if process else None
    items = repo.list_runs(process_id=pid, limit=limit)
    processes = repo.list_processes()
    process_names = {p.id: p.name for p in processes}
    process_runners = {p.id: p.runner for p in processes}
    out = [_summary(r, process_names, process_runners) for r in items]
    return RunsResponse(count=len(out), runs=out)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(name: str, run_id: str) -> RunDetail:
    repo = get_repo()
    r = repo.get_run(UUID(run_id))
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    return _detail(r)

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import boto3
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


class RunLogEntry(BaseModel):
    timestamp: str
    message: str
    log_stream: str


class RunLogsResponse(BaseModel):
    log_group: str
    log_stream: str | None = None
    entries: list[RunLogEntry]
    error: str | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _executor_log_group(name: str) -> str:
    safe_name = name.replace(".", "-")
    return f"/aws/lambda/cogent-{safe_name}-executor"


def _log_window(run: Run) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    created_at = _utc(run.created_at) or now
    completed_at = _utc(run.completed_at)
    start = created_at - timedelta(minutes=2)
    end_candidates = [now, created_at + timedelta(minutes=15)]
    if completed_at is not None:
        end_candidates.append(completed_at + timedelta(minutes=2))
    end = max(end_candidates)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _find_run_seed_events(logs, log_group: str, run_id: str, start_ms: int, end_ms: int) -> list[dict]:
    try:
        seed = logs.filter_log_events(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            filterPattern=run_id,
            limit=20,
        )
        events = seed.get("events", [])
        if events:
            return events
    except logs.exceptions.ResourceNotFoundException:
        raise
    except Exception as exc:
        logger.debug("CloudWatch seed filter fell back to scan for run %s: %s", run_id, exc)

    # CloudWatch filter patterns are less reliable for UUID-like strings than
    # the Logs Insights query behind the CW link, so fall back to scanning a
    # bounded slice of the run window and matching in Python.
    matched: list[dict] = []
    next_token: str | None = None
    scanned = 0
    max_scan = 500

    while scanned < max_scan:
        kwargs = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": min(100, max_scan - scanned),
        }
        if next_token:
            kwargs["nextToken"] = next_token

        page = logs.filter_log_events(**kwargs)
        events = page.get("events", [])
        scanned += len(events)
        matched.extend(event for event in events if run_id in event.get("message", ""))
        if matched:
            break

        candidate = page.get("nextToken")
        if not candidate or candidate == next_token:
            break
        next_token = candidate

    return matched


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
        created_at=_iso(r.created_at),
        completed_at=_iso(r.completed_at),
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
        created_at=_iso(r.created_at),
        completed_at=_iso(r.completed_at),
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


@router.get("/runs/{run_id}/logs", response_model=RunLogsResponse)
def get_run_logs(
    name: str,
    run_id: str,
    limit: int = Query(20, ge=1, le=100),
) -> RunLogsResponse:
    repo = get_repo()
    run = repo.get_run(UUID(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    log_group = _executor_log_group(name)
    start_ms, end_ms = _log_window(run)
    logs = boto3.client("logs", region_name="us-east-1")

    try:
        seed_events = _find_run_seed_events(logs, log_group, run_id, start_ms, end_ms)
    except logs.exceptions.ResourceNotFoundException:
        return RunLogsResponse(log_group=log_group, entries=[])
    except Exception as exc:
        logger.warning("Failed to locate CloudWatch logs for run %s: %s", run_id, exc)
        return RunLogsResponse(
            log_group=log_group,
            entries=[],
            error="CloudWatch log preview is unavailable from this environment.",
        )

    stream_name = next(
        (event.get("logStreamName") for event in seed_events if event.get("logStreamName")),
        None,
    )
    if not stream_name:
        return RunLogsResponse(log_group=log_group, entries=[])

    try:
        stream_events = logs.filter_log_events(
            logGroupName=log_group,
            logStreamNames=[stream_name],
            startTime=start_ms,
            endTime=end_ms,
            limit=limit,
        )
    except Exception as exc:
        logger.warning("Failed to fetch CloudWatch log preview for run %s: %s", run_id, exc)
        return RunLogsResponse(
            log_group=log_group,
            log_stream=stream_name,
            entries=[],
            error="CloudWatch log preview is unavailable from this environment.",
        )

    entries = [
        RunLogEntry(
            timestamp=datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc).isoformat(),
            message=event["message"].rstrip(),
            log_stream=event["logStreamName"],
        )
        for event in sorted(
            stream_events.get("events", []),
            key=lambda event: (event["timestamp"], event.get("eventId", "")),
        )
    ]

    return RunLogsResponse(log_group=log_group, log_stream=stream_name, entries=entries[:limit])

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import ALL_EPOCHS, Run
from cogos.files.store import FileStore
from dashboard.db import get_repo

router = APIRouter(tags=["cogos-runs"])


# ── Response models ─────────────────────────────────────────────────


class RunSummary(BaseModel):
    id: str
    epoch: int = 0
    process: str
    process_name: str | None = None
    executor: str | None = None
    required_tags: list[str] | None = None
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


def _format_session_log_entry(step: dict) -> str:
    labels = [str(step.get("type", "step"))]
    turn_number = step.get("turn_number")
    if isinstance(turn_number, int):
        labels.append(f"turn={turn_number}")
    stop_reason = step.get("stop_reason") or step.get("final_stop_reason")
    if isinstance(stop_reason, str) and stop_reason:
        labels.append(f"stop={stop_reason}")
    header = " | ".join(labels)
    return f"{header}\n{json.dumps(step, indent=2, sort_keys=True)}"


def _artifact_timestamp(payload: Any, fallback: datetime | None) -> str:
    if isinstance(payload, dict):
        for field in ("created_at", "finalized_at", "updated_at"):
            value = payload.get(field)
            if isinstance(value, str) and value:
                return value
    return _iso(fallback) or ""


def _artifact_message(kind: str, key: str, payload: Any) -> str:
    if kind == "step" and isinstance(payload, dict):
        return f"{_format_session_log_entry(payload)}\nkey={key}"

    labels = [kind]
    if isinstance(payload, dict):
        status = payload.get("status")
        if isinstance(status, str) and status:
            labels.append(f"status={status}")
        stop_reason = payload.get("stop_reason") or payload.get("final_stop_reason")
        if isinstance(stop_reason, str) and stop_reason:
            labels.append(f"stop={stop_reason}")
        last_completed_step = payload.get("last_completed_step")
        if isinstance(last_completed_step, int):
            labels.append(f"last_step={last_completed_step}")
        resumable = payload.get("resumable")
        if isinstance(resumable, bool):
            labels.append("resumable" if resumable else "not_resumable")
        latest_run_id = payload.get("latest_run_id")
        if isinstance(latest_run_id, str) and latest_run_id:
            labels.append(f"latest_run={latest_run_id}")
        return f"{' | '.join(labels)}\nkey={key}\n{json.dumps(payload, indent=2, sort_keys=True)}"

    return f"{kind}\nkey={key}\n{payload}"


def _read_artifact_content(
    store: FileStore,
    key: str,
    *,
    as_of: datetime | None = None,
) -> tuple[str | None, datetime | None]:
    if as_of is None:
        raw = store.get_content(key)
        file_model = store.get(key)
        return raw, _utc(file_model.updated_at) if file_model else None

    history = store.history(key)
    if not history:
        raw = store.get_content(key)
        file_model = store.get(key)
        return raw, _utc(file_model.updated_at) if file_model else None

    selected = None
    for version in history:
        created_at = _utc(version.created_at)
        if created_at is None or created_at <= as_of:
            selected = version
            continue
        break
    if selected is None:
        selected = history[0]
    return selected.content, _utc(selected.created_at)


def _build_artifact_entry(
    store: FileStore,
    key: str,
    *,
    kind: str,
    as_of: datetime | None = None,
) -> RunLogEntry | None:
    raw, artifact_dt = _read_artifact_content(store, key, as_of=as_of)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    return RunLogEntry(
        timestamp=_artifact_timestamp(payload, artifact_dt),
        message=_artifact_message(kind, key, payload),
        log_stream=key.rsplit("/", 1)[-1],
    )


def _session_log_preview(repo, run: Run, limit: int) -> RunLogsResponse | None:
    if not isinstance(run.snapshot, dict):
        return None

    final_key = run.snapshot.get("final_key")
    if not isinstance(final_key, str) or not final_key:
        return None

    store = FileStore(repo)
    final_raw = store.get_content(final_key)
    if final_raw is None:
        return None

    try:
        final_payload = json.loads(final_raw)
    except json.JSONDecodeError:
        return RunLogsResponse(
            log_group="CogOS session artifacts",
            entries=[],
            error="Session artifact metadata is invalid JSON.",
        )

    trigger_key = final_payload.get("trigger_key")
    steps_key = final_payload.get("steps_key")
    checkpoint_key = final_payload.get("checkpoint_key") or run.snapshot.get("checkpoint_key")
    manifest_key = final_payload.get("manifest_key") or run.snapshot.get("manifest_key")
    if not isinstance(steps_key, str) or not steps_key:
        return RunLogsResponse(
            log_group="CogOS session artifacts",
            entries=[],
            error="Session artifact metadata is missing steps.",
        )

    as_of = _utc(run.completed_at) or _utc(run.created_at)
    entries: list[RunLogEntry] = []

    if isinstance(trigger_key, str) and trigger_key:
        trigger_entry = _build_artifact_entry(store, trigger_key, kind="trigger")
        if trigger_entry is not None:
            entries.append(trigger_entry)

    step_files = store.list_files(prefix=steps_key, limit=max(limit * 5, 200))
    for artifact in step_files:
        entry = _build_artifact_entry(store, artifact.key, kind="step")
        if entry is not None:
            entries.append(entry)

    final_entry = _build_artifact_entry(store, final_key, kind="final")
    if final_entry is not None:
        entries.append(final_entry)

    if isinstance(checkpoint_key, str) and checkpoint_key:
        checkpoint_entry = _build_artifact_entry(store, checkpoint_key, kind="checkpoint", as_of=as_of)
        if checkpoint_entry is not None:
            entries.append(checkpoint_entry)

    if isinstance(manifest_key, str) and manifest_key:
        manifest_entry = _build_artifact_entry(store, manifest_key, kind="manifest", as_of=as_of)
        if manifest_entry is not None:
            entries.append(manifest_entry)

    return RunLogsResponse(
        log_group="CogOS session artifacts",
        log_stream=final_key.rsplit("/", 1)[0],
        entries=entries[-limit:],
    )


def _summary(
    r: Run,
    process_names: dict[UUID, str] | None = None,
    process_runners: dict[UUID, list[str]] | None = None,
    process_executors: dict[UUID, str] | None = None,
) -> RunSummary:
    return RunSummary(
        id=str(r.id),
        epoch=r.epoch,
        process=str(r.process),
        process_name=process_names.get(r.process) if process_names else None,
        executor=process_executors.get(r.process) if process_executors else None,
        required_tags=process_runners.get(r.process) if process_runners else None,
        event=str(r.message) if r.message else None,
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
        event=str(r.message) if r.message else None,
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
    epoch: str | None = Query(None, description="Epoch filter: omit for current, 'all' for all epochs"),
) -> RunsResponse:
    repo = get_repo()
    pid = UUID(process) if process else None
    ep = ALL_EPOCHS if epoch == "all" else None
    items = repo.list_runs(process_id=pid, limit=limit, epoch=ep)
    proc_epoch = ALL_EPOCHS if epoch == "all" else None
    processes = repo.list_processes(epoch=proc_epoch)
    process_names = {p.id: p.name for p in processes}
    process_runners = {p.id: p.required_tags for p in processes}
    process_executors = {p.id: p.executor for p in processes}
    out = [_summary(r, process_names, process_runners, process_executors) for r in items]
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

    session_preview = _session_log_preview(repo, run, limit)
    if session_preview is not None:
        return session_preview

    _ = name
    return RunLogsResponse(log_group="CogOS session artifacts", entries=[])

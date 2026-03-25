from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import ALL_EPOCHS, Handler, Process, ProcessMode, ProcessStatus
from cogos.db.models.process_capability import ProcessCapability
from cogos.files.context_engine import ContextEngine
from cogos.files.store import FileStore
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-processes"])


# ── Response / request models ──────────────────────────────────────


class ProcessSummary(BaseModel):
    id: str
    name: str
    mode: str
    executor: str = "llm"
    status: str
    priority: float
    required_tags: list[str] = []
    model: str | None = None
    preemptible: bool = False
    retry_count: int = 0
    max_retries: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ProcessDetail(BaseModel):
    id: str
    epoch: int = 0
    name: str
    mode: str
    executor: str = "llm"
    content: str
    priority: float
    resources: list[str]
    required_tags: list[str] = []
    status: str
    runnable_since: str | None = None
    parent_process: str | None = None
    preemptible: bool
    model: str | None = None
    model_constraints: dict
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int
    retry_count: int
    retry_backoff_ms: int | None = None
    clear_context: bool
    metadata: dict
    output_events: list[str] = []
    created_at: str | None = None
    updated_at: str | None = None


class CapGrantIn(BaseModel):
    grant_name: str
    capability_name: str
    config: dict | None = None


class ProcessCreate(BaseModel):
    name: str
    mode: str = "one_shot"
    content: str = ""
    priority: float = 0.0
    required_tags: list[str] = []
    status: str = "waiting"
    parent_process: str | None = None
    model: str | None = None
    model_constraints: dict | None = None
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int = 0
    preemptible: bool = False
    clear_context: bool = False
    metadata: dict | None = None
    output_events: list[str] | None = None
    cap_grants: list[CapGrantIn] | None = None  # named capability grants
    capabilities: list[str] | None = None  # legacy: capability names to grant
    capability_configs: dict[str, dict] | None = None  # legacy: per-capability config
    handlers: list[str] | None = None  # event patterns for handlers


class ProcessUpdate(BaseModel):
    name: str | None = None
    mode: str | None = None
    content: str | None = None
    priority: float | None = None
    required_tags: list[str] | None = None
    status: str | None = None
    model: str | None = None
    model_constraints: dict | None = None
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int | None = None
    preemptible: bool | None = None
    clear_context: bool | None = None
    metadata: dict | None = None
    output_events: list[str] | None = None
    cap_grants: list[CapGrantIn] | None = None  # named capability grants
    capabilities: list[str] | None = None  # legacy: capability names to grant
    capability_configs: dict[str, dict] | None = None  # legacy: per-capability config
    handlers: list[str] | None = None  # event patterns for handlers


class ProcessesResponse(BaseModel):
    cogent_name: str
    count: int
    processes: list[ProcessDetail]


# ── Helpers ─────────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _summary(p: Process) -> ProcessSummary:
    return ProcessSummary(
        id=str(p.id),
        name=p.name,
        mode=p.mode.value,
        executor=p.executor,
        status=p.status.value,
        priority=p.priority,
        required_tags=p.required_tags,
        model=p.model,
        preemptible=p.preemptible,
        retry_count=p.retry_count,
        max_retries=p.max_retries,
        created_at=_iso(p.created_at),
        updated_at=_iso(p.updated_at),
    )


def _detail(p: Process) -> ProcessDetail:
    return ProcessDetail(
        id=str(p.id),
        epoch=p.epoch,
        name=p.name,
        mode=p.mode.value,
        executor=p.executor,
        content=p.content,
        priority=p.priority,
        resources=[str(r) for r in p.resources],
        required_tags=p.required_tags,
        status=p.status.value,
        runnable_since=str(p.runnable_since) if p.runnable_since else None,
        parent_process=str(p.parent_process) if p.parent_process else None,
        preemptible=p.preemptible,
        model=p.model,
        model_constraints=p.model_constraints,
        return_schema=p.return_schema,
        max_duration_ms=p.max_duration_ms,
        max_retries=p.max_retries,
        retry_count=p.retry_count,
        retry_backoff_ms=p.retry_backoff_ms,
        clear_context=p.clear_context,
        metadata=p.metadata,
        output_events=p.output_events,
        created_at=_iso(p.created_at),
        updated_at=_iso(p.updated_at),
    )


def _sync_handlers(
    process_id: UUID,
    channel_names: list[str],
    repo,  # noqa: ANN001
) -> None:
    """Sync handlers: add missing, remove stale."""
    from cogos.db.models import Channel, ChannelType

    existing = repo.list_handlers(process_id=process_id)
    # Batch-fetch all channels once to map IDs to names
    all_channels = repo.list_channels(limit=500)
    channels_by_id = {ch.id: ch for ch in all_channels}
    channels_by_name = {ch.name: ch for ch in all_channels}

    existing_by_name: dict[str, Handler] = {}
    for h in existing:
        if h.channel:
            ch = channels_by_id.get(h.channel)
            if ch:
                existing_by_name[ch.name] = h

    desired = set(channel_names)

    # Add new
    for ch_name in desired - set(existing_by_name.keys()):
        ch = channels_by_name.get(ch_name)
        if not ch:
            ch = Channel(name=ch_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(ch)
        repo.create_handler(Handler(process=process_id, channel=ch.id))

    # Remove stale
    for name, h in existing_by_name.items():
        if name not in desired:
            repo.delete_handler(h.id)


def _sync_capabilities_from_grants(
    process_id: UUID,
    grants: list[CapGrantIn],
    repo,  # noqa: ANN001
) -> None:
    """Sync capability grants. Each grant has grant_name, capability_name, config."""
    existing = repo.list_process_capabilities(process_id)
    existing_by_name = {pc.name: pc for pc in existing}
    desired_names = {g.grant_name for g in grants}

    # Batch-fetch all capabilities once
    caps_by_name = {c.name: c for c in repo.list_capabilities()}

    for g in grants:
        c = caps_by_name.get(g.capability_name)
        if not c:
            continue
        cfg = g.config or {}
        if g.grant_name in existing_by_name:
            pc = existing_by_name[g.grant_name]
            if cfg != pc.config or pc.capability != c.id:
                pc.config = cfg
                pc.capability = c.id
                repo.create_process_capability(pc)
        else:
            repo.create_process_capability(
                ProcessCapability(
                    process=process_id,
                    capability=c.id,
                    name=g.grant_name,
                    config=cfg,
                ),
            )

    for name, pc in existing_by_name.items():
        if name not in desired_names:
            repo.delete_process_capability(pc.id)


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/process", response_model=ProcessesResponse)
def list_processes(
    name: str,
    status: str | None = Query(None, description="Filter by process status"),
    epoch: str | None = Query(None, description="Epoch filter: omit for current, 'all' for all epochs"),
    limit: int = Query(200, ge=1, le=500),
) -> ProcessesResponse:
    repo = get_repo()
    ps = ProcessStatus(status) if status else None
    ep = ALL_EPOCHS if epoch == "all" else None
    procs = repo.list_processes(status=ps, epoch=ep, limit=limit)

    details = [_detail(p) for p in procs]

    return ProcessesResponse(cogent_name=name, count=len(details), processes=details)


@router.get("/process/id/{process_id}")
def get_process(name: str, process_id: str) -> dict:
    repo = get_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    runs = repo.list_runs(process_id=p.id, limit=50)
    run_list = [
        {
            "id": str(r.id),
            "status": r.status.value,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "cost_usd": float(r.cost_usd),
            "duration_ms": r.duration_ms,
            "error": r.error,
            "result": r.result,
            "created_at": _iso(r.created_at),
            "completed_at": _iso(r.completed_at),
        }
        for r in runs
    ]

    # Resolve full prompt: file content + includes
    ctx = ContextEngine(FileStore(repo))
    resolved_prompt = ctx.generate_full_prompt(p)
    prompt_tree = ctx.resolve_prompt_tree(p)

    # Capabilities granted to this process — batch-fetch all capabilities
    pcs = repo.list_process_capabilities(p.id)
    all_caps = {c.id: c for c in repo.list_capabilities()}
    cap_grants: list[dict] = []
    for pc in pcs:
        c = all_caps.get(pc.capability)
        if c:
            cap_grants.append(
                {
                    "id": str(pc.id),
                    "grant_name": pc.name or c.name,
                    "capability_name": c.name,
                    "config": pc.config,
                }
            )

    # Global includes — files the executor prepends to every process prompt.
    file_store = FileStore(repo)
    include_files = file_store.list_files(prefix="cogos/includes/")
    includes = []
    for f in sorted(include_files, key=lambda f: f.key):
        fv = repo.get_active_file_version(f.id)
        if fv and fv.content:
            includes.append({"key": f.key, "content": fv.content})

    # Channel subscriptions (handlers) — batch-fetch channels
    handlers = repo.list_handlers(process_id=p.id)
    channel_ids = [h.channel for h in handlers if h.channel]
    channels_by_id = {ch.id: ch for ch in repo.list_channels(limit=500)} if channel_ids else {}
    handler_list = []
    for h in handlers:
        ch_name = None
        if h.channel:
            ch = channels_by_id.get(h.channel)
            ch_name = ch.name if ch else str(h.channel)
        handler_list.append({"id": str(h.id), "channel": ch_name, "enabled": h.enabled})

    capability_configs = {g["grant_name"]: g["config"] for g in cap_grants}

    return {
        "process": _detail(p).model_dump(),
        "runs": run_list,
        "resolved_prompt": resolved_prompt,
        "prompt_tree": prompt_tree,
        "capabilities": [g["grant_name"] for g in cap_grants],
        "capability_configs": capability_configs,
        "cap_grants": cap_grants,
        "includes": includes,
        "handlers": handler_list,
    }


@router.post("/process", response_model=ProcessDetail)
def create_process(name: str, body: ProcessCreate) -> ProcessDetail:
    repo = get_repo()
    p = Process(
        name=body.name,
        mode=ProcessMode(body.mode),
        content=body.content,
        priority=body.priority,
        required_tags=body.required_tags,
        status=ProcessStatus(body.status),
        parent_process=UUID(body.parent_process) if body.parent_process else None,
        model=body.model,
        model_constraints=body.model_constraints if body.model_constraints is not None else {},
        return_schema=body.return_schema,
        max_duration_ms=body.max_duration_ms,
        max_retries=body.max_retries,
        preemptible=body.preemptible,
        clear_context=body.clear_context,
        metadata=body.metadata if body.metadata is not None else {},
    )
    if body.output_events is not None:
        p.output_events = body.output_events
    repo.upsert_process(p)

    if body.cap_grants is not None:
        _sync_capabilities_from_grants(p.id, body.cap_grants, repo)
    elif body.capabilities is not None:
        # Legacy: convert capabilities list to grants
        configs = body.capability_configs if body.capability_configs is not None else {}
        grants = [CapGrantIn(grant_name=n, capability_name=n, config=configs.get(n)) for n in body.capabilities]
        _sync_capabilities_from_grants(p.id, grants, repo)
    if body.handlers is not None:
        _sync_handlers(p.id, body.handlers, repo)
    return _detail(p)


@router.put("/process/id/{process_id}", response_model=ProcessDetail)
def update_process(name: str, process_id: str, body: ProcessUpdate) -> ProcessDetail:
    repo = get_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    if body.name is not None:
        p.name = body.name
    if body.mode is not None:
        p.mode = ProcessMode(body.mode)
    if body.content is not None:
        p.content = body.content
    if body.priority is not None:
        p.priority = body.priority
    if body.required_tags is not None:
        p.required_tags = body.required_tags
    if body.status is not None:
        p.status = ProcessStatus(body.status)
    if body.model is not None:
        p.model = body.model
    if body.model_constraints is not None:
        p.model_constraints = body.model_constraints
    if body.return_schema is not None:
        p.return_schema = body.return_schema
    if body.max_duration_ms is not None:
        p.max_duration_ms = body.max_duration_ms
    if body.max_retries is not None:
        p.max_retries = body.max_retries
    if body.preemptible is not None:
        p.preemptible = body.preemptible
    if body.clear_context is not None:
        p.clear_context = body.clear_context
    if body.metadata is not None:
        p.metadata = body.metadata
    if body.output_events is not None:
        p.output_events = body.output_events

    repo.upsert_process(p)
    if body.cap_grants is not None:
        _sync_capabilities_from_grants(p.id, body.cap_grants, repo)
    elif body.capabilities is not None:
        configs = body.capability_configs if body.capability_configs is not None else {}
        grants = [CapGrantIn(grant_name=n, capability_name=n, config=configs.get(n)) for n in body.capabilities]
        _sync_capabilities_from_grants(p.id, grants, repo)
    if body.handlers is not None:
        _sync_handlers(p.id, body.handlers, repo)
    return _detail(p)


@router.post("/reboot")
def reboot_system(name: str) -> dict:
    """Kill all processes, clear process state, re-create init."""
    from cogos.runtime.reboot import reboot as do_reboot

    repo = get_repo()
    result = do_reboot(repo)
    return result


class ProcessLogEntry(BaseModel):
    stream: str  # "stdout" or "stderr"
    text: str
    process_name: str | None = None
    created_at: str | None = None


class ProcessLogsResponse(BaseModel):
    process_id: str
    process_name: str
    entries: list[ProcessLogEntry]


@router.get("/process/id/{process_id}/logs", response_model=ProcessLogsResponse)
def get_process_logs(
    name: str,
    process_id: str,
    limit: int = Query(100, le=500),
) -> ProcessLogsResponse:
    repo = get_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    entries: list[ProcessLogEntry] = []
    for stream in ("stdout", "stderr"):
        ch = repo.get_channel_by_name(f"process:{p.name}:{stream}")
        if not ch:
            continue
        msgs = repo.list_channel_messages(ch.id, limit=limit)
        for m in msgs:
            entries.append(
                ProcessLogEntry(
                    stream=stream,
                    text=m.payload.get("text", ""),
                    process_name=m.payload.get("process", p.name),
                    created_at=_iso(m.created_at) if m.created_at else None,
                )
            )

    # Sort by created_at — assert guarantees non-None, cast for pyright
    for e in entries:
        assert e.created_at is not None
    entries.sort(key=lambda e: cast(str, e.created_at))

    return ProcessLogsResponse(
        process_id=str(p.id),
        process_name=p.name,
        entries=entries,
    )


@router.delete("/process/id/{process_id}")
def delete_process(name: str, process_id: str) -> dict:
    repo = get_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")
    repo.delete_process(UUID(process_id))
    return {"deleted": True, "id": process_id}


@router.get("/process/name/{process_name}/prompt")
def get_process_prompt(name: str, process_name: str) -> dict:
    """Return the fully rendered prompt for a process looked up by name."""
    repo = get_repo()
    process = repo.get_process_by_name(process_name)
    if not process:
        raise HTTPException(status_code=404, detail=f"Process not found: {process_name}")

    ctx = ContextEngine(FileStore(repo))
    prompt = ctx.generate_full_prompt(process)
    return {"prompt": prompt}

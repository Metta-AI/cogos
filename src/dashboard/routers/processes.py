from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Handler, Process, ProcessMode, ProcessStatus
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
    status: str
    priority: float
    runner: str
    model: str | None = None
    preemptible: bool = False
    retry_count: int = 0
    max_retries: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ProcessDetail(BaseModel):
    id: str
    name: str
    mode: str
    content: str
    priority: float
    resources: list[str]
    runner: str
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
    runner: str = "lambda"
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
    runner: str | None = None
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
        status=p.status.value,
        priority=p.priority,
        runner=p.runner,
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
        name=p.name,
        mode=p.mode.value,
        content=p.content,
        priority=p.priority,
        resources=[str(r) for r in p.resources],
        runner=p.runner,
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
    # Build map of channel name -> handler
    existing_by_name: dict[str, object] = {}
    for h in existing:
        name = None
        if h.channel:
            ch = repo.get_channel(h.channel)
            name = ch.name if ch else None
        if name:
            existing_by_name[name] = h

    desired = set(channel_names)

    # Add new
    for ch_name in desired - set(existing_by_name.keys()):
        ch = repo.get_channel_by_name(ch_name)
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

    for g in grants:
        c = repo.get_capability_by_name(g.capability_name)
        if not c:
            continue
        cfg = g.config or None
        if g.grant_name in existing_by_name:
            pc = existing_by_name[g.grant_name]
            if (cfg or None) != pc.config or pc.capability != c.id:
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


@router.get("/processes", response_model=ProcessesResponse)
def list_processes(
    name: str,
    status: str | None = Query(None, description="Filter by process status"),
) -> ProcessesResponse:
    repo = get_repo()
    ps = ProcessStatus(status) if status else None
    procs = repo.list_processes(status=ps)

    details = [_detail(p) for p in procs]

    return ProcessesResponse(cogent_name=name, count=len(details), processes=details)


@router.get("/processes/{process_id}")
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

    # Capabilities granted to this process (named grants with scope config)
    pcs = repo.list_process_capabilities(p.id)
    cap_grants: list[dict] = []
    for pc in pcs:
        c = repo.get_capability(pc.capability)
        if c:
            cap_grants.append({
                "id": str(pc.id),
                "grant_name": pc.name or c.name,
                "capability_name": c.name,
                "config": pc.config,
            })

    # Global includes — files the executor prepends to every process prompt.
    file_store = FileStore(repo)
    include_files = file_store.list_files(prefix="cogos/includes/")
    includes = []
    for f in sorted(include_files, key=lambda f: f.key):
        fv = repo.get_active_file_version(f.id)
        if fv and fv.content:
            includes.append({"key": f.key, "content": fv.content})

    # Channel subscriptions (handlers)
    handlers = repo.list_handlers(process_id=p.id)
    handler_list = []
    for h in handlers:
        ch_name = None
        if h.channel:
            ch = repo.get_channel(h.channel)
            ch_name = ch.name if ch else str(h.channel)
        handler_list.append({"id": str(h.id), "channel": ch_name, "enabled": h.enabled})

    return {
        "process": _detail(p).model_dump(),
        "runs": run_list,
        "resolved_prompt": resolved_prompt,
        "prompt_tree": prompt_tree,
        "capabilities": [g["grant_name"] for g in cap_grants],
        "capability_configs": {
            g["grant_name"]: g["config"] or {}
            for g in cap_grants
        },
        "cap_grants": cap_grants,
        "includes": includes,
        "handlers": handler_list,
    }



@router.post("/processes", response_model=ProcessDetail)
def create_process(name: str, body: ProcessCreate) -> ProcessDetail:
    repo = get_repo()
    p = Process(
        name=body.name,
        mode=ProcessMode(body.mode),
        content=body.content,
        priority=body.priority,
        runner=body.runner,
        status=ProcessStatus(body.status),
        parent_process=UUID(body.parent_process) if body.parent_process else None,
        model=body.model,
        model_constraints=body.model_constraints or {},
        return_schema=body.return_schema,
        max_duration_ms=body.max_duration_ms,
        max_retries=body.max_retries,
        preemptible=body.preemptible,
        clear_context=body.clear_context,
        metadata=body.metadata or {},
    )
    if body.output_events is not None:
        p.output_events = body.output_events
    repo.upsert_process(p)
    if body.cap_grants is not None:
        _sync_capabilities_from_grants(p.id, body.cap_grants, repo)
    elif body.capabilities is not None:
        # Legacy: convert capabilities list to grants
        configs = body.capability_configs or {}
        grants = [CapGrantIn(grant_name=n, capability_name=n, config=configs.get(n)) for n in body.capabilities]
        _sync_capabilities_from_grants(p.id, grants, repo)
    if body.handlers is not None:
        _sync_handlers(p.id, body.handlers, repo)
    return _detail(p)


@router.put("/processes/{process_id}", response_model=ProcessDetail)
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
    if body.runner is not None:
        p.runner = body.runner
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
        configs = body.capability_configs or {}
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


@router.delete("/processes/{process_id}")
def delete_process(name: str, process_id: str) -> dict:
    repo = get_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")
    repo.delete_process(UUID(process_id))
    return {"deleted": True, "id": process_id}

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.db.models.file import File, FileVersion
from cogos.db.models.process_capability import ProcessCapability
from dashboard.db import get_cogos_repo

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
    code: str | None = None
    files: list[str]
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
    created_at: str | None = None
    updated_at: str | None = None


class ProcessCreate(BaseModel):
    name: str
    mode: str = "one_shot"
    content: str = ""
    files: list[str] | None = None  # file keys for prompt templates
    priority: float = 0.0
    runner: str = "lambda"
    status: str = "waiting"
    model: str | None = None
    model_constraints: dict | None = None
    return_schema: dict | None = None
    max_duration_ms: int | None = None
    max_retries: int = 0
    preemptible: bool = False
    clear_context: bool = False
    metadata: dict | None = None
    capabilities: list[str] | None = None  # capability names to grant
    capability_configs: dict[str, dict] | None = None  # per-capability config keyed by name


class ProcessUpdate(BaseModel):
    name: str | None = None
    mode: str | None = None
    content: str | None = None
    files: list[str] | None = None  # file keys for prompt templates
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
    capabilities: list[str] | None = None  # capability names to grant
    capability_configs: dict[str, dict] | None = None  # per-capability config keyed by name


class ProcessesResponse(BaseModel):
    cogent_name: str
    count: int
    processes: list[ProcessDetail]


# ── Helpers ─────────────────────────────────────────────────────────


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
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


def _detail(p: Process) -> ProcessDetail:
    return ProcessDetail(
        id=str(p.id),
        name=p.name,
        mode=p.mode.value,
        content=p.content,
        code=str(p.code) if p.code else None,
        files=[str(f) for f in p.files],
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
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


def _resolve_file_key(key: str, repo, *, create: bool = False) -> UUID | None:  # noqa: ANN001
    """Resolve a file key to a UUID, or None. Optionally create if missing."""
    if not key:
        return None
    f = repo.get_file_by_key(key)
    if f:
        return f.id
    if create:
        f = File(key=key)
        repo.insert_file(f)
        fv = FileVersion(file_id=f.id, version=1, content="", source="dashboard")
        repo.insert_file_version(fv)
        return f.id
    return None


def _resolve_file_keys(keys: list[str], repo, *, create: bool = False) -> list[UUID]:  # noqa: ANN001
    """Resolve a list of file keys to UUIDs, optionally creating missing files."""
    result: list[UUID] = []
    for key in keys:
        uid = _resolve_file_key(key, repo, create=create)
        if uid:
            result.append(uid)
    return result


def _sync_capabilities(
    process_id: UUID,
    cap_names: list[str],
    repo,  # noqa: ANN001
    configs: dict[str, dict] | None = None,
) -> None:
    """Sync granted capabilities: add missing, remove stale, update configs."""
    existing = repo.list_process_capabilities(process_id)
    existing_cap_ids = {pc.capability: pc for pc in existing}

    configs = configs or {}

    # Build desired: cap_id -> config
    desired: dict[UUID, dict] = {}
    for name in cap_names:
        c = repo.get_capability_by_name(name)
        if c:
            desired[c.id] = configs.get(name, {})

    # name lookup for existing caps
    cap_id_to_name: dict[UUID, str] = {}
    for name in cap_names:
        c = repo.get_capability_by_name(name)
        if c:
            cap_id_to_name[c.id] = name

    # Add new
    for cid in set(desired.keys()) - set(existing_cap_ids.keys()):
        cfg = desired.get(cid, {})
        repo.create_process_capability(
            ProcessCapability(process=process_id, capability=cid, config=cfg or None),
        )

    # Update existing configs (upsert handles ON CONFLICT)
    for cid, pc in existing_cap_ids.items():
        if cid in desired:
            new_cfg = desired.get(cid, {})
            if (new_cfg or None) != pc.config:
                pc.config = new_cfg or None
                repo.create_process_capability(pc)

    # Remove stale
    for cid, pc in existing_cap_ids.items():
        if cid not in desired:
            repo.delete_process_capability(pc.id)


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/processes", response_model=ProcessesResponse)
def list_processes(
    name: str,
    status: str | None = Query(None, description="Filter by process status"),
) -> ProcessesResponse:
    repo = get_cogos_repo()
    ps = ProcessStatus(status) if status else None
    procs = repo.list_processes(status=ps)

    # Annotate with run counts
    all_runs = repo.list_runs(limit=10000)
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    windows = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    run_counts: dict[str, dict[str, dict[str, int]]] = {}
    for r in all_runs:
        pid = str(r.process)
        if pid not in run_counts:
            run_counts[pid] = {k: {"runs": 0, "failed": 0} for k in windows}
        run_time = r.created_at or r.completed_at
        is_failed = r.status and r.status.value in ("failed", "timeout")
        if run_time:
            age = now - run_time
            for label, window in windows.items():
                if age <= window:
                    run_counts[pid][label]["runs"] += 1
                    if is_failed:
                        run_counts[pid][label]["failed"] += 1

    details = [_detail(p) for p in procs]

    return ProcessesResponse(cogent_name=name, count=len(details), processes=details)


@router.get("/processes/{process_id}")
def get_process(name: str, process_id: str) -> dict:
    repo = get_cogos_repo()
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
            "created_at": str(r.created_at) if r.created_at else None,
            "completed_at": str(r.completed_at) if r.completed_at else None,
        }
        for r in runs
    ]

    # Resolve full prompt: file content + includes
    resolved_prompt = _resolve_process_prompt(p, repo)

    # Capabilities granted to this process
    pcs = repo.list_process_capabilities(p.id)
    cap_names: list[str] = []
    cap_configs: dict[str, dict] = {}
    for pc in pcs:
        c = repo.get_capability(pc.capability)
        if c:
            cap_names.append(c.name)
            if pc.config:
                cap_configs[c.name] = pc.config

    # File keys
    file_keys: list[str] = []
    for fid in p.files:
        f = repo.get_file_by_id(fid)
        if f:
            file_keys.append(f.key)

    return {
        "process": _detail(p).model_dump(),
        "runs": run_list,
        "resolved_prompt": resolved_prompt,
        "capabilities": cap_names,
        "capability_configs": cap_configs,
        "file_keys": file_keys,
    }


def _resolve_process_prompt(p: Process, repo) -> str:  # noqa: ANN001
    """Build the full composed prompt for a process by resolving file includes."""
    sections: list[str] = []

    # System prompts from linked files
    visited: set[str] = set()
    for fid in (p.files or []):
        f = repo.get_file_by_id(fid)
        if not f or f.key in visited:
            continue
        visited.add(f.key)
        fv = repo.get_active_file_version(f.id)
        if fv:
            sections.append(f"## File: {f.key}\n\n{fv.content}")
        if f.includes:
            _resolve_file_includes(f.includes, visited, sections, repo)

    # Legacy: single code FK
    if p.code and not p.files:
        f = repo.get_file_by_id(p.code)
        if f and f.key not in visited:
            visited.add(f.key)
            fv = repo.get_active_file_version(f.id)
            if fv:
                sections.append(f"## File: {f.key}\n\n{fv.content}")
            if f.includes:
                _resolve_file_includes(f.includes, visited, sections, repo)

    # User message from process.content
    if p.content:
        sections.append(f"## Process Content\n\n{p.content}")

    return "\n\n---\n\n".join(sections) if sections else p.content or ""


def _resolve_file_includes(
    keys: list[str], visited: set[str], sections: list[str], repo,  # noqa: ANN001
) -> None:
    """Recursively resolve file includes, appending content to sections."""
    for key in keys:
        if key in visited:
            continue
        visited.add(key)
        f = repo.get_file_by_key(key)
        if not f:
            continue
        fv = repo.get_active_file_version(f.id)
        if fv:
            sections.append(f"## Included File: {f.key}\n\n{fv.content}")
        if f.includes:
            _resolve_file_includes(f.includes, visited, sections, repo)


@router.post("/processes", response_model=ProcessDetail)
def create_process(name: str, body: ProcessCreate) -> ProcessDetail:
    repo = get_cogos_repo()
    p = Process(
        name=body.name,
        mode=ProcessMode(body.mode),
        content=body.content,
        files=_resolve_file_keys(body.files or [], repo, create=True),
        priority=body.priority,
        runner=body.runner,
        status=ProcessStatus(body.status),
        model=body.model,
        model_constraints=body.model_constraints or {},
        return_schema=body.return_schema,
        max_duration_ms=body.max_duration_ms,
        max_retries=body.max_retries,
        preemptible=body.preemptible,
        clear_context=body.clear_context,
        metadata=body.metadata or {},
    )
    repo.upsert_process(p)
    if body.capabilities is not None:
        _sync_capabilities(p.id, body.capabilities, repo, configs=body.capability_configs)
    return _detail(p)


@router.put("/processes/{process_id}", response_model=ProcessDetail)
def update_process(name: str, process_id: str, body: ProcessUpdate) -> ProcessDetail:
    repo = get_cogos_repo()
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
    if body.files is not None:
        p.files = _resolve_file_keys(body.files, repo, create=True)

    repo.upsert_process(p)
    if body.capabilities is not None:
        _sync_capabilities(p.id, body.capabilities, repo, configs=body.capability_configs)
    return _detail(p)


@router.delete("/processes/{process_id}")
def delete_process(name: str, process_id: str) -> dict:
    repo = get_cogos_repo()
    p = repo.get_process(UUID(process_id))
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")
    repo.execute(
        "DELETE FROM cogos_process WHERE id = :id",
        {"id": UUID(process_id)},
    )
    return {"deleted": True, "id": process_id}

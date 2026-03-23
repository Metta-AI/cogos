"""Executor registry API — register, heartbeat, list, and manage channel executors."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from cogos.api.auth import AuthContext, validate_token
from dashboard.db import get_repo

router = APIRouter(tags=["executors"])


# ── Request / Response Models ─────────────────────────────────


class RegisterRequest(BaseModel):
    executor_id: str
    channel_type: str = "claude-code"
    capabilities: list[str] = []
    metadata: dict[str, Any] = {}


class RegisterResponse(BaseModel):
    executor_id: str
    heartbeat_interval_s: int = 30
    status: str = "registered"


class HeartbeatRequest(BaseModel):
    status: str = "idle"  # "idle" | "busy"
    current_run_id: str | None = None
    resource_usage: dict[str, Any] | None = None


class HeartbeatResponse(BaseModel):
    ok: bool


class RunCompleteRequest(BaseModel):
    executor_id: str
    status: str  # "completed" | "failed" | "timeout"
    output: dict[str, Any] | None = None
    tokens_used: dict[str, int] | None = None
    duration_ms: int | None = None
    error: str | None = None


class ExecutorItem(BaseModel):
    id: str
    executor_id: str
    channel_type: str = "claude-code"
    capabilities: list[str] = []
    metadata: dict[str, Any] = {}
    status: str = "idle"
    current_run_id: str | None = None
    last_heartbeat_at: str | None = None
    registered_at: str | None = None


class ExecutorsResponse(BaseModel):
    cogent_name: str
    count: int = 0
    executors: list[ExecutorItem] = []


class CreateTokenRequest(BaseModel):
    name: str


class CreateTokenResponse(BaseModel):
    name: str
    token: str  # raw token, shown once only
    launch_command: str


class TokenItem(BaseModel):
    name: str
    scope: str = "executor"
    created_at: str | None = None
    revoked: bool = False


class TokensResponse(BaseModel):
    tokens: list[TokenItem]


# ── Endpoints ─────────────────────────────────────────────────


@router.get("/executors", response_model=ExecutorsResponse)
def list_executors(name: str, status: str | None = None):
    """List all registered executors."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()
    filter_status = ExecutorStatus(status) if status else None
    executors = repo.list_executors(status=filter_status)
    items = [
        ExecutorItem(
            id=str(e.id),
            executor_id=e.executor_id,
            channel_type=e.channel_type,
            capabilities=e.capabilities,
            metadata=e.metadata,
            status=e.status.value,
            current_run_id=str(e.current_run_id) if e.current_run_id else None,
            last_heartbeat_at=str(e.last_heartbeat_at) if e.last_heartbeat_at else None,
            registered_at=str(e.registered_at) if e.registered_at else None,
        )
        for e in executors
    ]
    return ExecutorsResponse(cogent_name=name, count=len(items), executors=items)


@router.get("/executors/{executor_id}", response_model=ExecutorItem)
def get_executor(name: str, executor_id: str):
    """Get a single executor by its executor_id."""
    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    return ExecutorItem(
        id=str(e.id),
        executor_id=e.executor_id,
        channel_type=e.channel_type,
        capabilities=e.capabilities,
        metadata=e.metadata,
        status=e.status.value,
        current_run_id=str(e.current_run_id) if e.current_run_id else None,
        last_heartbeat_at=str(e.last_heartbeat_at) if e.last_heartbeat_at else None,
        registered_at=str(e.registered_at) if e.registered_at else None,
    )


@router.post("/executors/register", response_model=RegisterResponse)
def register_executor(
    name: str,
    body: RegisterRequest,
    auth: AuthContext = Depends(validate_token),
):
    """Register a channel executor with the cogent."""
    from cogos.db.models import Executor

    repo = get_repo()

    executor = Executor(
        executor_id=body.executor_id,
        channel_type=body.channel_type,
        capabilities=body.capabilities,
        metadata=body.metadata,
    )
    repo.register_executor(executor)

    return RegisterResponse(
        executor_id=body.executor_id,
        heartbeat_interval_s=30,
        status="registered",
    )


@router.post("/executors/{executor_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    name: str,
    executor_id: str,
    body: HeartbeatRequest,
    auth: AuthContext = Depends(validate_token),
):
    """Send a heartbeat from an executor."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()

    status = ExecutorStatus(body.status) if body.status in ("idle", "busy") else ExecutorStatus.IDLE
    run_id = UUID(body.current_run_id) if body.current_run_id else None

    found = repo.heartbeat_executor(
        executor_id,
        status=status,
        current_run_id=run_id,
        resource_usage=body.resource_usage,
    )
    if not found:
        raise HTTPException(status_code=404, detail="executor not found")

    return HeartbeatResponse(ok=True)


@router.post("/executors/{executor_id}/drain")
def drain_executor(name: str, executor_id: str):
    """Stop dispatching to an executor (mark it stale so it drains)."""
    from cogos.db.models import ExecutorStatus

    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    repo.update_executor_status(executor_id, ExecutorStatus.STALE)
    return {"ok": True, "executor_id": executor_id, "status": "stale"}


@router.delete("/executors/{executor_id}")
def remove_executor(name: str, executor_id: str):
    """Remove an executor from the registry."""
    repo = get_repo()
    e = repo.get_executor(executor_id)
    if not e:
        raise HTTPException(status_code=404, detail="executor not found")
    repo.delete_executor(executor_id)
    return {"ok": True, "executor_id": executor_id}


@router.post("/runs/{run_id}/complete")
def complete_run(
    name: str,
    run_id: str,
    body: RunCompleteRequest,
    auth: AuthContext = Depends(validate_token),
):
    """Report run completion from a channel executor."""
    from cogos.db.models import ExecutorStatus, RunStatus

    repo = get_repo()

    run_uuid = UUID(run_id)
    status_map = {
        "completed": RunStatus.COMPLETED,
        "failed": RunStatus.FAILED,
        "timeout": RunStatus.TIMEOUT,
    }
    run_status = status_map.get(body.status, RunStatus.FAILED)

    tokens_in = (body.tokens_used or {}).get("input", 0)
    tokens_out = (body.tokens_used or {}).get("output", 0)

    repo.complete_run(
        run_uuid,
        status=run_status,
        error=body.error,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=body.duration_ms,
    )

    # Release executor back to idle
    repo.update_executor_status(body.executor_id, ExecutorStatus.IDLE)

    return {"ok": True, "run_id": run_id, "status": body.status}


# ── Token Management ──────────────────────────────────────────


@router.post("/executor-tokens", response_model=CreateTokenResponse)
def create_token(name: str, body: CreateTokenRequest, request: Request):
    """Create a new executor token. Returns the raw token once."""
    import hashlib
    import secrets

    from cogos.db.models import ExecutorToken

    repo = get_repo()
    raw_token = secrets.token_urlsafe(32)
    token = ExecutorToken(
        name=body.name,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
    )
    repo.create_executor_token(token)

    api_url = str(request.base_url).rstrip("/")
    launch_cmd = f"COGOS_API_KEY={raw_token} COGOS_API_URL={api_url} COGOS_COGENT_NAME={name} claude"

    return CreateTokenResponse(
        name=body.name,
        token=raw_token,
        launch_command=launch_cmd,
    )


@router.get("/executor-tokens", response_model=TokensResponse)
def list_tokens(name: str):
    """List all executor tokens (without raw values)."""
    repo = get_repo()
    tokens = repo.list_executor_tokens()
    items = [
        TokenItem(
            name=t.name,
            scope=t.scope,
            created_at=str(t.created_at) if t.created_at else None,
            revoked=t.revoked_at is not None,
        )
        for t in tokens
    ]
    return TokensResponse(tokens=items)


@router.delete("/executor-tokens/{token_name}")
def revoke_token(name: str, token_name: str):
    """Revoke an executor token by name."""
    repo = get_repo()
    revoked = repo.revoke_executor_token(token_name)
    if not revoked:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True, "name": token_name}

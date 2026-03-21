"""Session management — executor bootstrap and introspection."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from cogos_api.auth import TokenClaims, create_session_token, get_claims, verify_executor_key
from cogos_api.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


# ── Request / Response models ─────────────────────────────────


class CreateSessionRequest(BaseModel):
    process_id: str
    cogent: str = ""


class CreateSessionResponse(BaseModel):
    token: str
    process_id: str
    cogent: str
    expires_at: float


class SessionInfo(BaseModel):
    process_id: str
    cogent: str
    issued_at: float
    expires_at: float
    process_name: str = ""
    capabilities: list[str] = []


# ── Routes ────────────────────────────────────────────────────


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session(body: CreateSessionRequest, request: Request) -> CreateSessionResponse:
    """Create a session token for a remote executor.

    Authenticates via X-Executor-Key header (pre-shared key).
    """
    executor_key = request.headers.get("x-executor-key", "")
    if not executor_key or not verify_executor_key(executor_key):
        raise HTTPException(status_code=403, detail="Invalid executor key")

    # Validate UUID format first (before DB call)
    try:
        pid = UUID(body.process_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid process_id format")

    # Validate process exists
    repo = get_repo()

    process = repo.get_process(pid)
    if process is None:
        raise HTTPException(status_code=404, detail="Process not found")

    cogent = body.cogent or process.name
    token = create_session_token(str(pid), cogent)

    # Decode to get expiry
    from cogos_api.auth import verify_token

    claims = verify_token(token)

    return CreateSessionResponse(
        token=token,
        process_id=str(pid),
        cogent=cogent,
        expires_at=claims.expires_at,
    )


@router.get("/sessions/me", response_model=SessionInfo)
def get_session_info(claims: TokenClaims = Depends(get_claims)) -> SessionInfo:
    """Introspect the current session — process info, capabilities, TTL."""
    repo = get_repo()
    pid = UUID(claims.process_id)
    process = repo.get_process(pid)
    process_name = process.name if process else ""

    # List capability grant names for this process
    cap_names: list[str] = []
    pcs = repo.list_process_capabilities(pid)
    for pc in pcs:
        cap = repo.get_capability(pc.capability)
        if cap and cap.enabled:
            cap_names.append(pc.name or cap.name.split("/")[0])

    return SessionInfo(
        process_id=claims.process_id,
        cogent=claims.cogent,
        issued_at=claims.issued_at,
        expires_at=claims.expires_at,
        process_name=process_name,
        capabilities=sorted(cap_names),
    )

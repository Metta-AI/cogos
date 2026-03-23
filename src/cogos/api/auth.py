"""Token-based authentication for the CogOS API.

All endpoints validate a Bearer token by SHA-256 hashing it and looking
up the hash in the executor_tokens table. Capability proxy routes also
accept an X-Process-Id header to identify the calling process.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

from cogos.api.db import get_repo

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Validated auth context from a Bearer token."""
    token_name: str
    process_id: str  # from X-Process-Id header, empty if not provided


def validate_token(request: Request) -> AuthContext:
    """FastAPI dependency -- validate Bearer token against stored ExecutorToken hashes.

    Accepts token from either Authorization: Bearer or x-api-key header.
    Also reads optional X-Process-Id header for capability proxy routes.
    """
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key", "")

    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:]
    elif api_key:
        token = api_key

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    repo = get_repo()
    executor_token = repo.get_executor_token_by_hash(token_hash)
    if executor_token is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    process_id = request.headers.get("x-process-id", "")

    return AuthContext(
        token_name=executor_token.name,
        process_id=process_id,
    )

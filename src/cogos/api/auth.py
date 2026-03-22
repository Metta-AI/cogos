"""JWT-based authentication for the CogOS API.

Executors obtain a session token via POST /api/v1/sessions using a pre-shared
executor key.  All subsequent capability calls use Bearer <jwt>.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_cached_signing_key: str | None = None
_signing_key_lock = threading.Lock()


def _get_signing_key() -> str:
    """Return the JWT signing key, caching after first load."""
    global _cached_signing_key
    if _cached_signing_key is not None:
        return _cached_signing_key

    with _signing_key_lock:
        # Double-check after acquiring lock
        if _cached_signing_key is not None:
            return _cached_signing_key

        from cogos.api.config import settings

        # Prefer explicit env var
        if settings.jwt_secret:
            _cached_signing_key = settings.jwt_secret
            return _cached_signing_key

        # Fall back to Secrets Manager
        if settings.jwt_secret_id:
            try:
                import json

                import boto3

                sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
                resp = sm.get_secret_value(SecretId=settings.jwt_secret_id)
                raw = resp["SecretString"]
                # Accept both plain string and JSON {"key": "..."}
                try:
                    data = json.loads(raw)
                    _cached_signing_key = data.get("key", raw)
                except (json.JSONDecodeError, TypeError):
                    _cached_signing_key = raw
                assert _cached_signing_key is not None
                return _cached_signing_key
            except Exception:
                logger.warning("Could not load JWT signing key from Secrets Manager", exc_info=True)

        raise RuntimeError("No JWT signing key configured — set COGOS_API_JWT_SECRET or configure jwt_secret_id")


def _get_executor_key() -> str:
    """Return the pre-shared executor bootstrap key."""
    from cogos.api.config import settings

    if settings.executor_key:
        return settings.executor_key

    if settings.executor_key_secret_id:
        try:
            import json

            import boto3

            sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            resp = sm.get_secret_value(SecretId=settings.executor_key_secret_id)
            raw = resp["SecretString"]
            try:
                data = json.loads(raw)
                return data.get("key", raw)
            except (json.JSONDecodeError, TypeError):
                return raw
        except Exception:
            logger.warning("Could not load executor key from Secrets Manager", exc_info=True)

    cogent = os.environ.get("COGENT", "")
    if cogent:
        secret_id = f"cogent/{cogent}/executor-api-key"
        try:
            import json

            import boto3

            sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            resp = sm.get_secret_value(SecretId=secret_id)
            raw = resp["SecretString"]
            try:
                data = json.loads(raw)
                return data.get("key", raw)
            except (json.JSONDecodeError, TypeError):
                return raw
        except Exception:
            logger.warning("Could not load executor key for cogent %s", cogent, exc_info=True)

    raise RuntimeError("No executor key configured — set COGOS_API_EXECUTOR_KEY")


@dataclass
class TokenClaims:
    """Decoded JWT claims for a session token."""

    process_id: str
    cogent: str
    issued_at: float
    expires_at: float


def create_session_token(process_id: str, cogent: str, *, ttl: int | None = None) -> str:
    """Create a signed JWT for an executor session."""
    from cogos.api.config import settings

    now = time.time()
    if ttl is None:
        ttl = settings.jwt_ttl_seconds

    payload = {
        "sub": process_id,
        "cogent": cogent,
        "iat": int(now),
        "exp": int(now + ttl),
    }
    return jwt.encode(payload, _get_signing_key(), algorithm="HS256")


def verify_token(token: str) -> TokenClaims:
    """Verify a JWT and return decoded claims.  Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _get_signing_key(), algorithms=["HS256"])
    return TokenClaims(
        process_id=payload["sub"],
        cogent=payload["cogent"],
        issued_at=payload["iat"],
        expires_at=payload["exp"],
    )


def verify_executor_key(key: str) -> bool:
    """Check the executor bootstrap key."""
    try:
        expected = _get_executor_key()
        return bool(expected) and key == expected
    except RuntimeError:
        return False


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_claims(request: Request) -> TokenClaims:
    """FastAPI dependency — extract and verify JWT from Authorization header."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise _unauthorized("Missing or invalid Authorization header")

    token = auth[7:]
    try:
        return verify_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError as exc:
        raise _unauthorized(f"Invalid token: {exc}")


def _unauthorized(detail: str) -> Any:
    from fastapi import HTTPException

    return HTTPException(status_code=401, detail=detail)

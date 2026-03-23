"""Cogtainer-level endpoints (not cogent-scoped)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogtainer"])


@router.get("/api/cogtainer/cogents")
def list_cogents() -> dict:
    """List all cogents on the current cogtainer, plus the current cogent name."""
    current = os.environ.get("COGENT", "")
    try:
        from cogtainer.runtime.factory import create_executor_runtime

        runtime = create_executor_runtime()
        names = runtime.list_cogents()
    except Exception:
        logger.warning("Could not list cogents from runtime", exc_info=True)
        names = []
    return {"cogents": names, "current": current}

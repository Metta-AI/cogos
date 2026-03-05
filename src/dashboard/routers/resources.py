from __future__ import annotations

from fastapi import APIRouter

from dashboard.database import fetch_all
from dashboard.models import ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
async def list_resources(name: str) -> ResourcesResponse:
    rows = await fetch_all(
        "SELECT id::text, context_key, cli_session_id "
        "FROM conversations WHERE cogent_id = $1 AND status = 'active'",
        name,
    )
    return ResourcesResponse(
        cogent_id=name,
        active_sessions=len(rows),
        conversations=rows,
    )

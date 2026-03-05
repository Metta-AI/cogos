from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(name: str) -> ResourcesResponse:
    repo = get_repo()
    rows = repo.query(
        "SELECT id::text, context_key, cli_session_id "
        "FROM conversations WHERE cogent_id = :cid AND status = 'active'",
        {"cid": name},
    )
    return ResourcesResponse(
        cogent_id=name,
        active_sessions=len(rows),
        conversations=rows,
    )

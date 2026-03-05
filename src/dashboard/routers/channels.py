from __future__ import annotations

from fastapi import APIRouter

from dashboard.database import fetch_all
from dashboard.models import ChannelsResponse

router = APIRouter(tags=["channels"])


@router.get("/channels", response_model=ChannelsResponse)
async def list_channels(name: str) -> ChannelsResponse:
    rows = await fetch_all(
        "SELECT name, type, enabled, created_at::text "
        "FROM channels WHERE cogent_id = $1 ORDER BY name",
        name,
    )
    return ChannelsResponse(cogent_id=name, count=len(rows), channels=rows)

from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import Channel, ChannelsResponse

router = APIRouter(tags=["channels"])


@router.get("/channels", response_model=ChannelsResponse)
def list_channels(name: str) -> ChannelsResponse:
    repo = get_repo()
    rows = repo.query(
        "SELECT name, type, enabled, created_at::text "
        "FROM channels ORDER BY name",
    )
    channels = [Channel(**r) for r in rows]
    return ChannelsResponse(cogent_name=name, count=len(channels), channels=channels)

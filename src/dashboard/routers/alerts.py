from __future__ import annotations

from fastapi import APIRouter

from dashboard.database import fetch_all
from dashboard.models import AlertsResponse

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
async def list_alerts(name: str) -> AlertsResponse:
    rows = await fetch_all(
        "SELECT id::text, severity, alert_type, source, message, metadata, "
        "created_at::text FROM alerts WHERE cogent_id = $1 "
        "AND resolved_at IS NULL ORDER BY created_at DESC",
        name,
    )
    return AlertsResponse(cogent_id=name, count=len(rows), alerts=rows)

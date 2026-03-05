from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import Alert, AlertsResponse

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
def list_alerts(name: str) -> AlertsResponse:
    repo = get_repo()
    rows = repo.query(
        "SELECT id::text, severity, alert_type, source, message, metadata, "
        "created_at::text FROM alerts WHERE cogent_id = :cid "
        "AND resolved_at IS NULL ORDER BY created_at DESC",
        {"cid": name},
    )
    alerts = [Alert(**r) for r in rows]
    return AlertsResponse(cogent_id=name, count=len(alerts), alerts=alerts)

from __future__ import annotations

import json as _json
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dashboard.db import get_repo

router = APIRouter(tags=["alerts"])


class AlertItem(BaseModel):
    id: str
    severity: str
    alert_type: str
    source: str
    message: str
    metadata: dict | None = None
    resolved_at: str | None = None
    created_at: str | None = None


class AlertsResponse(BaseModel):
    count: int
    alerts: list[AlertItem]


class AlertCreate(BaseModel):
    severity: str = "warning"
    alert_type: str = ""
    source: str = ""
    message: str
    metadata: dict = {}


def _fmt(row: dict) -> AlertItem:
    meta = row.get("metadata")
    if isinstance(meta, str):
        meta = _json.loads(meta)
    return AlertItem(
        id=str(row.get("id", "")),
        severity=row.get("severity", ""),
        alert_type=row.get("alert_type", ""),
        source=row.get("source", ""),
        message=row.get("message", ""),
        metadata=meta,
        resolved_at=str(row["resolved_at"]) if row.get("resolved_at") else None,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


@router.get("/alerts", response_model=AlertsResponse)
def list_alerts(
    name: str,
    resolved: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
) -> AlertsResponse:
    repo = get_repo()
    rows = repo.list_alerts(resolved=resolved, limit=limit)
    items = [_fmt(r) for r in rows]
    return AlertsResponse(count=len(items), alerts=items)


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(name: str, alert_id: str) -> dict:
    repo = get_repo()
    repo.resolve_alert(UUID(alert_id))
    return {"ok": True}


@router.post("/alerts/resolve-all")
def resolve_all_alerts(name: str) -> dict:
    repo = get_repo()
    unresolved = repo.list_alerts(resolved=False, limit=500)
    for row in unresolved:
        repo.resolve_alert(UUID(str(row["id"])))
    return {"ok": True, "resolved": len(unresolved)}


@router.post("/alerts", response_model=AlertItem)
def create_alert_endpoint(name: str, body: AlertCreate) -> AlertItem:
    repo = get_repo()
    repo.create_alert(
        severity=body.severity,
        alert_type=body.alert_type,
        source=body.source,
        message=body.message,
        metadata=body.metadata,
    )
    # Return the latest alert (just created)
    rows = repo.list_alerts(resolved=False, limit=1)
    return _fmt(rows[0]) if rows else AlertItem(
        id="", severity=body.severity, alert_type=body.alert_type,
        source=body.source, message=body.message,
    )


@router.delete("/alerts/{alert_id}")
def delete_alert(name: str, alert_id: str) -> dict:
    repo = get_repo()
    repo._execute(
        "DELETE FROM alerts WHERE id = :id",
        [repo._param("id", UUID(alert_id))],
    )
    return {"ok": True}

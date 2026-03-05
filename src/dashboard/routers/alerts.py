from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter

from brain.db.models import Alert as DBAlert, AlertSeverity
from dashboard.db import get_repo
from dashboard.models import Alert, AlertCreate, AlertsResponse

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertsResponse)
def list_alerts(name: str) -> AlertsResponse:
    repo = get_repo()
    db_alerts = repo.get_unresolved_alerts()
    alerts = [
        Alert(
            id=str(a.id),
            severity=a.severity.value if a.severity else None,
            alert_type=a.alert_type,
            source=a.source,
            message=a.message,
            metadata=a.metadata,
            resolved_at=str(a.resolved_at) if a.resolved_at else None,
            created_at=str(a.created_at) if a.created_at else None,
        )
        for a in db_alerts
    ]
    return AlertsResponse(cogent_name=name, count=len(alerts), alerts=alerts)


@router.get("/alerts/resolved", response_model=AlertsResponse)
def list_resolved_alerts(name: str, limit: int = 25) -> AlertsResponse:
    repo = get_repo()
    db_alerts = repo.get_resolved_alerts(limit)
    alerts = [
        Alert(
            id=str(a.id),
            severity=a.severity.value if a.severity else None,
            alert_type=a.alert_type,
            source=a.source,
            message=a.message,
            metadata=a.metadata,
            resolved_at=str(a.resolved_at) if a.resolved_at else None,
            created_at=str(a.created_at) if a.created_at else None,
        )
        for a in db_alerts
    ]
    return AlertsResponse(cogent_name=name, count=len(alerts), alerts=alerts)


@router.post("/alerts/resolve-all")
def resolve_all_alerts(name: str) -> dict:
    repo = get_repo()
    count = repo.resolve_all_alerts()
    return {"resolved_count": count}


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(name: str, alert_id: str) -> dict:
    repo = get_repo()
    resolved = repo.resolve_alert(UUID(alert_id))
    return {"resolved": resolved}


@router.post("/alerts", response_model=Alert)
def create_alert(name: str, body: AlertCreate) -> Alert:
    repo = get_repo()
    severity = AlertSeverity(body.severity) if body.severity else AlertSeverity.WARNING
    db_alert = DBAlert(
        id=uuid4(),
        severity=severity,
        alert_type=body.alert_type,
        source=body.source,
        message=body.message,
        metadata=body.metadata,
    )
    repo.create_alert(db_alert)
    return Alert(
        id=str(db_alert.id),
        severity=db_alert.severity.value if db_alert.severity else None,
        alert_type=db_alert.alert_type,
        source=db_alert.source,
        message=db_alert.message,
        metadata=db_alert.metadata,
        resolved_at=str(db_alert.resolved_at) if db_alert.resolved_at else None,
        created_at=str(db_alert.created_at) if db_alert.created_at else None,
    )


@router.delete("/alerts/{alert_id}")
def delete_alert(name: str, alert_id: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_alert(UUID(alert_id))
    return {"deleted": deleted}

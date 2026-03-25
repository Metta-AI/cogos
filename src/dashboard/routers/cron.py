from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from cogos.db.models import Cron
from dashboard.db import get_repo
from dashboard.models import (
    CronCreate,
    CronItem,
    CronsResponse,
    CronUpdate,
    ToggleRequest,
    ToggleResponse,
)

router = APIRouter(tags=["cron"])


def _cron_to_item(c: Cron) -> CronItem:
    assert c.payload is not None
    return CronItem(
        id=str(c.id),
        cron_expression=c.expression,
        channel_name=c.channel_name,
        enabled=c.enabled,
        metadata=c.payload,
        created_at=str(c.created_at) if c.created_at else None,
    )


@router.get("/cron", response_model=CronsResponse)
def list_cron(name: str) -> CronsResponse:
    repo = get_repo()
    rules = repo.list_cron_rules(enabled_only=False)
    items = [_cron_to_item(c) for c in rules]
    return CronsResponse(cogent_name=name, count=len(items), crons=items)


@router.post("/cron", response_model=CronItem)
def create_cron(name: str, body: CronCreate) -> CronItem:
    repo = get_repo()
    cron = Cron(
        expression=body.cron_expression,
        channel_name=body.channel_name,
        enabled=body.enabled,
        payload=body.metadata if body.metadata is not None else {},
    )
    repo.upsert_cron(cron)
    return _cron_to_item(cron)


@router.put("/cron/{cron_id}", response_model=CronItem)
def update_cron(name: str, cron_id: str, body: CronUpdate) -> CronItem:
    repo = get_repo()
    uid = UUID(cron_id)

    # Find existing
    existing = [c for c in repo.list_cron_rules() if c.id == uid]
    if not existing:
        raise HTTPException(status_code=404, detail="Cron not found")

    cron = existing[0]

    if body.enabled is not None:
        repo.update_cron_enabled(uid, body.enabled)
        cron.enabled = body.enabled

    if body.cron_expression is not None or body.channel_name is not None or body.metadata is not None:
        repo.delete_cron(uid)
        updated = Cron(
            id=uid,
            expression=body.cron_expression if body.cron_expression is not None else cron.expression,
            channel_name=body.channel_name if body.channel_name is not None else cron.channel_name,
            enabled=body.enabled if body.enabled is not None else cron.enabled,
            payload=body.metadata if body.metadata is not None else cron.payload,
        )
        repo.upsert_cron(updated)
        cron = updated

    return _cron_to_item(cron)


@router.delete("/cron/{cron_id}")
def delete_cron(name: str, cron_id: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_cron(UUID(cron_id))
    return {"deleted": deleted}


@router.post("/cron/toggle", response_model=ToggleResponse)
def toggle_cron(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = 0
    for cid_str in body.ids:
        if repo.update_cron_enabled(UUID(cid_str), body.enabled):
            count += 1
    return ToggleResponse(updated=count, enabled=body.enabled)

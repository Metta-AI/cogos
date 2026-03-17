from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dashboard.db import get_repo

router = APIRouter(tags=["cogos-operations"])


class OperationSummary(BaseModel):
    id: str
    epoch: int
    type: str
    metadata: dict
    created_at: str | None = None


class OperationsResponse(BaseModel):
    count: int
    operations: list[OperationSummary]


@router.get("/operations", response_model=OperationsResponse)
def list_operations(
    name: str,
    limit: int = Query(50, ge=1, le=200),
) -> OperationsResponse:
    repo = get_repo()
    ops = repo.list_operations(limit=limit)
    out = [
        OperationSummary(
            id=str(op.id),
            epoch=op.epoch,
            type=op.type,
            metadata=op.metadata,
            created_at=op.created_at.isoformat() if op.created_at else None,
        )
        for op in ops
    ]
    return OperationsResponse(count=len(out), operations=out)

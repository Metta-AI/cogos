from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import ResourceItem, ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(name: str) -> ResourcesResponse:
    repo = get_repo()
    resources = repo.list_resources()
    items = []
    for r in resources:
        assert r.metadata is not None
        items.append(
            ResourceItem(
                name=r.name,
                resource_type=r.resource_type.value,
                capacity=r.capacity,
                used=0.0,
                metadata=r.metadata,
                created_at=str(r.created_at) if r.created_at else None,
            )
        )
    return ResourcesResponse(cogent_name=name, count=len(items), resources=items)

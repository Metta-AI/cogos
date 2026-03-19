from __future__ import annotations

from fastapi import APIRouter

from dashboard.db import get_repo
from dashboard.models import ResourceItem, ResourcesResponse

router = APIRouter(tags=["resources"])


@router.get("/resources", response_model=ResourcesResponse)
def list_resources(name: str) -> ResourcesResponse:
    repo = get_repo()
    resources = repo.list_resources() if hasattr(repo, "list_resources") else []  # type: ignore[attr-defined]
    items = [
        ResourceItem(
            name=r.name,
            resource_type=r.resource_type.value if hasattr(r.resource_type, "value") else str(r.resource_type),
            capacity=r.capacity,
            used=0.0,
            metadata=r.metadata or {},
            created_at=str(r.created_at) if r.created_at else None,
        )
        for r in resources
    ]
    return ResourcesResponse(cogent_name=name, count=len(items), resources=items)

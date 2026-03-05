from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query

from dashboard.db import get_repo
from dashboard.models import MemoryItem, MemoryResponse

router = APIRouter(tags=["memory"])


def _try_parse_json(val: Any) -> Any:
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return val
    return val


def _derive_group(name: str) -> str:
    if "/" in name:
        return name.rsplit("/", 1)[0]
    if "-" in name:
        return name.split("-", 1)[0]
    return ""


@router.get("/memory", response_model=MemoryResponse)
def list_memory(
    name: str,
    scope: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> MemoryResponse:
    repo = get_repo()

    if scope:
        rows = repo.query(
            "SELECT id::text, scope, type, name, content, provenance, "
            "created_at::text, updated_at::text "
            "FROM memory WHERE scope = :scope "
            "ORDER BY name, scope LIMIT :lim",
            {"scope": scope, "lim": limit},
        )
    else:
        rows = repo.query(
            "SELECT id::text, scope, type, name, content, provenance, "
            "created_at::text, updated_at::text "
            "FROM memory "
            "ORDER BY name, scope LIMIT :lim",
            {"lim": limit},
        )

    items = [
        MemoryItem(
            id=r["id"],
            scope=r.get("scope"),
            type=r.get("type"),
            name=r.get("name", ""),
            group=_derive_group(r.get("name", "")),
            content=r.get("content", ""),
            provenance=_try_parse_json(r.get("provenance")),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]
    return MemoryResponse(cogent_name=name, count=len(items), memory=items)

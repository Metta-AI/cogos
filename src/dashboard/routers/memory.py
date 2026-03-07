from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from brain.db.models import Memory, MemoryVersion
from dashboard.db import get_repo
from dashboard.models import MemoryCreate, MemoryItem, MemoryResponse, MemoryUpdate, MemoryVersionItem
from memory.store import MemoryStore

router = APIRouter(tags=["memory"])


def _derive_group(name: str) -> str:
    if "/" in name:
        return name.rsplit("/", 1)[0]
    if "-" in name:
        return name.split("-", 1)[0]
    return ""


def _version_to_item(mv: MemoryVersion) -> MemoryVersionItem:
    return MemoryVersionItem(
        id=str(mv.id),
        version=mv.version,
        content=mv.content,
        source=mv.source,
        read_only=mv.read_only,
        created_at=str(mv.created_at) if mv.created_at else None,
    )


def _memory_to_item(m: Memory) -> MemoryItem:
    active_mv = m.versions.get(m.active_version)
    return MemoryItem(
        id=str(m.id),
        name=m.name,
        group=_derive_group(m.name),
        active_version=m.active_version,
        content=active_mv.content if active_mv else "",
        source=active_mv.source if active_mv else "cogent",
        read_only=active_mv.read_only if active_mv else False,
        created_at=str(m.created_at) if m.created_at else None,
        modified_at=str(m.modified_at) if m.modified_at else None,
        versions=[
            _version_to_item(mv)
            for mv in sorted(m.versions.values(), key=lambda v: v.version)
        ],
    )


def _get_store() -> MemoryStore:
    return MemoryStore(get_repo())


@router.get("/memory", response_model=MemoryResponse)
def list_memory(
    name: str,
    prefix: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> MemoryResponse:
    store = _get_store()
    memories = store.list_memories(prefix=prefix, source=source, limit=limit)
    items = [_memory_to_item(m) for m in memories]
    return MemoryResponse(cogent_name=name, count=len(items), memory=items)


@router.post("/memory", response_model=MemoryItem)
def create_memory(name: str, body: MemoryCreate) -> MemoryItem:
    store = _get_store()
    mem = store.create(
        body.name,
        body.content,
        source=body.source,
        read_only=body.read_only,
    )
    return _memory_to_item(mem)


@router.put("/memory/{memory_name:path}", response_model=MemoryItem)
def update_memory(name: str, memory_name: str, body: MemoryUpdate) -> MemoryItem:
    store = _get_store()
    existing = store.get(memory_name)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")

    content = body.content
    if content is None:
        active_mv = existing.versions.get(existing.active_version)
        content = active_mv.content if active_mv else ""

    result = store.upsert(
        memory_name,
        content,
        source=body.source or "cogent",
        read_only=body.read_only if body.read_only is not None else False,
    )

    # Re-fetch the full memory to return
    updated = store.get(memory_name)
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found after update")
    return _memory_to_item(updated)


@router.delete("/memory/{memory_name:path}")
def delete_memory_endpoint(name: str, memory_name: str) -> dict:
    store = _get_store()
    try:
        store.delete(memory_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}

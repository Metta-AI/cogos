from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dashboard.db import get_repo
from dashboard.models import (
    ToggleRequest,
    ToggleResponse,
    ToolItem,
    ToolUpdate,
    ToolsResponse,
)

router = APIRouter(tags=["tools"])


def _tool_to_item(t) -> ToolItem:
    return ToolItem(
        id=str(t.id),
        name=t.name,
        description=t.description,
        instructions=t.instructions,
        input_schema=t.input_schema,
        handler=t.handler,
        iam_role_arn=t.iam_role_arn,
        enabled=t.enabled,
        metadata=t.metadata,
        created_at=str(t.created_at) if t.created_at else None,
        updated_at=str(t.updated_at) if t.updated_at else None,
    )


@router.get("/tools", response_model=ToolsResponse)
def list_tools(name: str, prefix: str | None = None) -> ToolsResponse:
    repo = get_repo()
    db_tools = repo.list_tools(prefix=prefix, enabled_only=False)
    tools = [_tool_to_item(t) for t in db_tools]
    return ToolsResponse(cogent_name=name, count=len(tools), tools=tools)


@router.get("/tools/{tool_name:path}", response_model=ToolItem)
def get_tool(name: str, tool_name: str) -> ToolItem:
    repo = get_repo()
    tool = repo.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _tool_to_item(tool)


@router.put("/tools/{tool_name:path}", response_model=ToolItem)
def update_tool(name: str, tool_name: str, body: ToolUpdate) -> ToolItem:
    repo = get_repo()
    existing = repo.get_tool(tool_name)
    if not existing:
        raise HTTPException(status_code=404, detail="Tool not found")

    if body.description is not None:
        existing.description = body.description
    if body.instructions is not None:
        existing.instructions = body.instructions
    if body.input_schema is not None:
        existing.input_schema = body.input_schema
    if body.enabled is not None:
        existing.enabled = body.enabled
    if body.metadata is not None:
        existing.metadata = body.metadata

    repo.upsert_tool(existing)
    return _tool_to_item(existing)


@router.post("/tools/toggle", response_model=ToggleResponse)
def toggle_tools(name: str, body: ToggleRequest) -> ToggleResponse:
    repo = get_repo()
    count = 0
    for tool_name in body.ids:
        if repo.update_tool_enabled(tool_name, body.enabled):
            count += 1
    return ToggleResponse(updated=count, enabled=body.enabled)


@router.delete("/tools/{tool_name:path}")
def delete_tool(name: str, tool_name: str) -> dict:
    repo = get_repo()
    deleted = repo.delete_tool(tool_name)
    return {"deleted": deleted}

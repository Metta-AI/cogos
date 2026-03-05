from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from dashboard.database import fetch_all, fetch_one
from dashboard.models import TasksResponse

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TasksResponse)
async def list_tasks(
    name: str,
    status: str | None = Query(None, description="Filter by task status"),
) -> TasksResponse:
    if status:
        rows = await fetch_all(
            "SELECT id::text, title, description, status, priority, source, "
            "external_id, metadata, error, created_at::text, updated_at::text, "
            "completed_at::text FROM tasks WHERE cogent_id = $1 AND status = $2 "
            "ORDER BY created_at DESC",
            name,
            status,
        )
    else:
        rows = await fetch_all(
            "SELECT id::text, title, description, status, priority, source, "
            "external_id, metadata, error, created_at::text, updated_at::text, "
            "completed_at::text FROM tasks WHERE cogent_id = $1 "
            "ORDER BY created_at DESC",
            name,
        )
    return TasksResponse(cogent_id=name, count=len(rows), tasks=rows)


@router.get("/tasks/{task_id}")
async def get_task(name: str, task_id: str) -> dict:
    task = await fetch_one(
        "SELECT id::text, title, description, status, priority, source, "
        "external_id, metadata, error, created_at::text, updated_at::text, "
        "completed_at::text FROM tasks WHERE id = $1::uuid AND cogent_id = $2",
        task_id,
        name,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    events = await fetch_all(
        "SELECT id::text, event_type, source, payload, created_at::text "
        "FROM events WHERE cogent_id = $1 AND payload::text LIKE '%' || $2 || '%' "
        "ORDER BY created_at DESC LIMIT 50",
        name,
        task_id,
    )

    created_at = task.get("created_at")
    completed_at = task.get("completed_at")
    executions = await fetch_all(
        "SELECT id::text, skill_name, status, started_at::text, "
        "completed_at::text, duration_ms, tokens_input, tokens_output, "
        "cost_usd::float, error FROM executions WHERE cogent_id = $1 "
        "AND started_at >= $2 AND ($3 IS NULL OR started_at <= $3) "
        "ORDER BY started_at DESC LIMIT 50",
        name,
        created_at,
        completed_at,
    )

    conversations = await fetch_all(
        "SELECT id::text, context_key, status, started_at::text, "
        "last_active::text FROM conversations WHERE cogent_id = $1 "
        "AND context_key LIKE '%' || $2 || '%'",
        name,
        task_id,
    )

    return {
        "task": task,
        "events": events,
        "executions": executions,
        "conversations": conversations,
    }

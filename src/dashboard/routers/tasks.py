from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from dashboard.db import get_repo
from dashboard.models import Task, TasksResponse

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TasksResponse)
def list_tasks(
    name: str,
    status: str | None = Query(None, description="Filter by task status"),
) -> TasksResponse:
    repo = get_repo()
    if status:
        rows = repo.query(
            "SELECT id::text, name, description, status, priority, creator, "
            "parent_task_id::text, source_event, limits, metadata, "
            "created_at::text, updated_at::text, completed_at::text "
            "FROM tasks WHERE status = :status "
            "ORDER BY created_at DESC",
            {"status": status},
        )
    else:
        rows = repo.query(
            "SELECT id::text, name, description, status, priority, creator, "
            "parent_task_id::text, source_event, limits, metadata, "
            "created_at::text, updated_at::text, completed_at::text "
            "FROM tasks ORDER BY created_at DESC",
        )
    tasks = [Task(**r) for r in rows]
    return TasksResponse(cogent_name=name, count=len(tasks), tasks=tasks)


@router.get("/tasks/{task_id}")
def get_task(name: str, task_id: str) -> dict:
    repo = get_repo()

    task = repo.query_one(
        "SELECT id::text, name, description, status, priority, creator, "
        "parent_task_id::text, source_event, limits, metadata, "
        "created_at::text, updated_at::text, completed_at::text "
        "FROM tasks WHERE id = :tid::uuid",
        {"tid": task_id},
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    runs = repo.query(
        "SELECT id::text, program_name, status, started_at::text, "
        "completed_at::text, duration_ms, tokens_input, tokens_output, "
        "cost_usd::float, error FROM runs WHERE task_id = :tid::uuid "
        "ORDER BY started_at DESC LIMIT 50",
        {"tid": task_id},
    )

    return {
        "task": task,
        "runs": runs,
    }

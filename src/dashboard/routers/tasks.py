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
            "SELECT id::text, title, description, status, priority, source, "
            "external_id, metadata, error, created_at::text, updated_at::text, "
            "completed_at::text FROM tasks WHERE cogent_id = :cid AND status = :status "
            "ORDER BY created_at DESC",
            {"cid": name, "status": status},
        )
    else:
        rows = repo.query(
            "SELECT id::text, title, description, status, priority, source, "
            "external_id, metadata, error, created_at::text, updated_at::text, "
            "completed_at::text FROM tasks WHERE cogent_id = :cid "
            "ORDER BY created_at DESC",
            {"cid": name},
        )
    tasks = [Task(**r) for r in rows]
    return TasksResponse(cogent_id=name, count=len(tasks), tasks=tasks)


@router.get("/tasks/{task_id}")
def get_task(name: str, task_id: str) -> dict:
    repo = get_repo()

    task = repo.query_one(
        "SELECT id::text, title, description, status, priority, source, "
        "external_id, metadata, error, created_at::text, updated_at::text, "
        "completed_at::text FROM tasks WHERE id = :tid::uuid AND cogent_id = :cid",
        {"tid": task_id, "cid": name},
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    events = repo.query(
        "SELECT id::text, event_type, source, payload, created_at::text "
        "FROM events WHERE cogent_id = :cid AND payload::text LIKE '%' || :tid || '%' "
        "ORDER BY created_at DESC LIMIT 50",
        {"cid": name, "tid": task_id},
    )

    created_at = task.get("created_at")
    completed_at = task.get("completed_at")
    runs = repo.query(
        "SELECT id::text, program_name, status, started_at::text, "
        "completed_at::text, duration_ms, tokens_input, tokens_output, "
        "cost_usd::float, error FROM runs WHERE cogent_id = :cid "
        "AND started_at >= :start AND (:end IS NULL OR started_at <= :end) "
        "ORDER BY started_at DESC LIMIT 50",
        {"cid": name, "start": created_at, "end": completed_at},
    )

    conversations = repo.query(
        "SELECT id::text, context_key, status, started_at::text, "
        "last_active::text FROM conversations WHERE cogent_id = :cid "
        "AND context_key LIKE '%' || :tid || '%'",
        {"cid": name, "tid": task_id},
    )

    return {
        "task": task,
        "events": events,
        "executions": runs,
        "conversations": conversations,
    }

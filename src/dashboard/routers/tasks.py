from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from brain.db.models import Task as DbTask, TaskStatus
from dashboard.db import get_repo
from dashboard.models import Task, TaskCreate, TaskUpdate, TasksResponse

router = APIRouter(tags=["tasks"])


def _task_to_response(t: DbTask) -> Task:
    return Task(
        id=str(t.id),
        name=t.name,
        description=t.description,
        program_name=t.program_name,
        content=t.content,
        status=t.status.value if t.status else None,
        priority=t.priority,
        runner=t.runner,
        clear_context=t.clear_context,
        memory_keys=t.memory_keys,
        tools=t.tools,
        resources=t.resources,
        creator=t.creator,
        parent_task_id=str(t.parent_task_id) if t.parent_task_id else None,
        source_event=t.source_event,
        limits=t.limits,
        metadata=t.metadata,
        created_at=str(t.created_at) if t.created_at else None,
        updated_at=str(t.updated_at) if t.updated_at else None,
        completed_at=str(t.completed_at) if t.completed_at else None,
    )


@router.get("/tasks", response_model=TasksResponse)
def list_tasks(
    name: str,
    status: str | None = Query(None, description="Filter by task status"),
) -> TasksResponse:
    repo = get_repo()
    task_status = TaskStatus(status) if status else None
    db_tasks = repo.list_tasks(status=task_status)
    tasks = [_task_to_response(t) for t in db_tasks]

    # Annotate with last run info and run counts
    from datetime import datetime, timedelta
    all_runs = repo.query_runs(limit=10000)
    now = datetime.utcnow()
    windows = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    # Build lookup: task_id -> most recent run and run counts
    last_run_by_task: dict[str, object] = {}
    run_counts_by_task: dict[str, dict[str, int]] = {}
    for r in all_runs:
        if r.task_id:
            tid = str(r.task_id)
            if tid not in last_run_by_task:
                last_run_by_task[tid] = r
            if tid not in run_counts_by_task:
                run_counts_by_task[tid] = {k: 0 for k in windows}
            run_time = r.started_at or r.completed_at
            if run_time:
                age = now - run_time
                for label, window in windows.items():
                    if age <= window:
                        run_counts_by_task[tid][label] += 1

    for t in tasks:
        r = last_run_by_task.get(t.id)
        if r:
            t.last_run_status = r.status.value if r.status else None
            t.last_run_error = r.error
            t.last_run_at = str(r.completed_at or r.started_at) if (r.completed_at or r.started_at) else None
        t.run_counts = run_counts_by_task.get(t.id, {k: 0 for k in windows})

    return TasksResponse(cogent_name=name, count=len(tasks), tasks=tasks)


@router.post("/tasks", response_model=Task)
def create_task(name: str, body: TaskCreate) -> Task:
    repo = get_repo()
    db_task = DbTask(
        name=body.name,
        description=body.description,
        content=body.content,
        program_name=body.program_name,
        status=TaskStatus(body.status),
        priority=body.priority,
        runner=body.runner,
        clear_context=body.clear_context,
        memory_keys=body.memory_keys or [],
        tools=body.tools or [],
        resources=body.resources or [],
        creator=body.creator,
        source_event=body.source_event,
        limits=body.limits or {},
        metadata=body.metadata or {},
    )
    repo.create_task(db_task)
    return _task_to_response(db_task)


@router.put("/tasks/{task_id}", response_model=Task)
def update_task(name: str, task_id: str, body: TaskUpdate) -> Task:
    repo = get_repo()
    t = repo.get_task(UUID(task_id))
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    if body.name is not None:
        t.name = body.name
    if body.description is not None:
        t.description = body.description
    if body.content is not None:
        t.content = body.content
    if body.program_name is not None:
        t.program_name = body.program_name
    if body.status is not None:
        t.status = TaskStatus(body.status)
        if t.status == TaskStatus.COMPLETED:
            from datetime import datetime
            t.completed_at = datetime.utcnow()
    if body.priority is not None:
        t.priority = body.priority
    if body.runner is not None:
        t.runner = body.runner
    if body.clear_context is not None:
        t.clear_context = body.clear_context
    if body.memory_keys is not None:
        t.memory_keys = body.memory_keys
    if body.tools is not None:
        t.tools = body.tools
    if body.resources is not None:
        t.resources = body.resources
    if body.creator is not None:
        t.creator = body.creator
    if body.source_event is not None:
        t.source_event = body.source_event
    if body.limits is not None:
        t.limits = body.limits
    if body.metadata is not None:
        t.metadata = body.metadata

    repo.update_task(t)
    return _task_to_response(t)


@router.delete("/tasks/{task_id}")
def delete_task(name: str, task_id: str) -> dict:
    repo = get_repo()
    if not repo.delete_task(UUID(task_id)):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True, "id": task_id}


@router.get("/tasks/{task_id}")
def get_task(name: str, task_id: str) -> dict:
    repo = get_repo()
    t = repo.get_task(UUID(task_id))
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    all_runs = repo.query_runs(limit=10000)
    db_runs = [r for r in all_runs if r.task_id and str(r.task_id) == task_id][:50]
    runs = [
        {
            "id": str(r.id),
            "program_name": r.program_name,
            "status": r.status.value if r.status else None,
            "started_at": str(r.started_at) if r.started_at else None,
            "completed_at": str(r.completed_at) if r.completed_at else None,
            "duration_ms": r.duration_ms,
            "tokens_input": r.tokens_input,
            "tokens_output": r.tokens_output,
            "cost_usd": float(r.cost_usd) if r.cost_usd else 0,
            "error": r.error,
        }
        for r in db_runs
    ]

    return {"task": _task_to_response(t).model_dump(), "runs": runs}

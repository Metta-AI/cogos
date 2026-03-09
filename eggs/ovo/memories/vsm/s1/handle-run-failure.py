"""handle-run-failure: Returns task to runnable on hard errors, detects stuck tasks.

Triggered by run:failed event.
"""

from __future__ import annotations

from uuid import UUID

from brain.db.models import Event, TaskStatus
from brain.db.repository import Repository

MAX_CONSECUTIVE_FAILURES = 3


def run(repo: Repository, event: dict, config: dict) -> list[Event]:
    """Handle a failed run: return task to runnable or emit stuck alert."""
    payload = event.get("payload", {})
    task_id_str = payload.get("task_id")
    run_id_str = payload.get("run_id")
    error = payload.get("error", "unknown error")

    if not task_id_str:
        return []

    task = repo.get_task(UUID(task_id_str))
    if not task:
        return []

    # Log failure in task metadata
    failures = task.metadata.get("failures", [])
    failures.append({
        "run_id": run_id_str,
        "error": error[:500],
    })
    task.metadata["failures"] = failures[-10:]  # Keep last 10
    task.metadata["last_failure"] = error[:500]

    # Count recent consecutive failures
    consecutive = len(failures)

    # Return to runnable (update_task persists metadata changes too)
    task.status = TaskStatus.RUNNABLE
    repo.update_task(task)

    events: list[Event] = []

    # If too many consecutive failures, emit stuck alert
    if consecutive >= MAX_CONSECUTIVE_FAILURES:
        events.append(
            Event(
                event_type="task:stuck",
                source="handle-run-failure",
                payload={
                    "task_id": str(task.id),
                    "task_name": task.name,
                    "consecutive_failures": consecutive,
                    "last_error": error[:500],
                },
            )
        )

    return events

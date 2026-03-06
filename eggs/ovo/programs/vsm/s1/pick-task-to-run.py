"""pick-task-to-run: Softmax scheduler that selects runnable tasks and emits dispatch events.

Triggered by scheduler:tick cron event.
"""

from __future__ import annotations

import math
import random

from brain.db.models import Event, ResourceType, TaskStatus
from brain.db.repository import Repository


def run(repo: Repository, event: dict, config: dict) -> list[Event]:
    """Pick runnable tasks via softmax sampling over priority, respecting resource limits."""
    # 1. Load all runnable tasks
    runnable = repo.list_tasks(status=TaskStatus.RUNNABLE, limit=500)
    if not runnable:
        return []

    # 2. Load resource capacities and compute availability
    all_resources = repo.list_resources()
    resource_map = {r.name: r for r in all_resources}

    available: dict[str, float] = {}
    for r in all_resources:
        if r.resource_type == ResourceType.POOL:
            used = repo.get_pool_usage(r.name)
            available[r.name] = r.capacity - used
        else:
            used = repo.get_consumable_usage(r.name)
            available[r.name] = r.capacity - used

    # 3. Filter to tasks whose resources are all available
    eligible = []
    for task in runnable:
        runner = task.runner or "lambda"
        needed = {"concurrent-tasks", runner}
        needed.update(task.resources)

        if all(available.get(r, 0) > 0 for r in needed):
            eligible.append(task)

    if not eligible:
        return []

    # 4. Read temperature from memory
    temp_records = repo.get_memories_by_names(["/vsm/s1/task-priority-temperature"])
    temperature = 1.0
    if temp_records:
        try:
            temperature = float(temp_records[0].content.strip())
        except (ValueError, IndexError):
            pass
    if temperature <= 0:
        temperature = 1.0

    # 5. Softmax over priorities
    priorities = [t.priority for t in eligible]
    max_p = max(priorities)
    exps = [math.exp((p - max_p) / temperature) for p in priorities]
    total = sum(exps)
    probs = [e / total for e in exps]

    # 6. Determine how many tasks we can dispatch (limited by concurrent-tasks)
    max_dispatch = int(available.get("concurrent-tasks", 1))
    num_to_pick = min(max_dispatch, len(eligible))

    # 7. Sample without replacement
    selected = []
    remaining_indices = list(range(len(eligible)))
    remaining_probs = list(probs)

    for _ in range(num_to_pick):
        if not remaining_indices:
            break
        # Normalize remaining probs
        total_p = sum(remaining_probs)
        if total_p <= 0:
            break
        normalized = [p / total_p for p in remaining_probs]

        # Sample
        r = random.random()
        cumulative = 0.0
        chosen_idx = 0
        for i, p in enumerate(normalized):
            cumulative += p
            if r <= cumulative:
                chosen_idx = i
                break

        task = eligible[remaining_indices[chosen_idx]]

        # Check that this task's runner still has capacity
        runner = task.runner or "lambda"
        if available.get(runner, 0) <= 0:
            remaining_indices.pop(chosen_idx)
            remaining_probs.pop(chosen_idx)
            continue

        selected.append(task)
        available[runner] = available.get(runner, 0) - 1
        available["concurrent-tasks"] = available.get("concurrent-tasks", 0) - 1

        remaining_indices.pop(chosen_idx)
        remaining_probs.pop(chosen_idx)

    # 8. Emit task:run events (handled directly by the orchestrator)
    events = []
    for task in selected:
        runner = task.runner or "lambda"
        events.append(
            Event(
                event_type="task:run",
                source="pick-task-to-run",
                payload={
                    "task_id": str(task.id),
                    "task_name": task.name,
                    "program_name": task.program_name,
                    "runner": runner,
                    "clear_context": task.clear_context,
                },
            )
        )

    return events

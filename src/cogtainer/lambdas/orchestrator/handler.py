"""Orchestrator Lambda: receives EventBridge events, matches triggers, dispatches executors.

Flow:
  EventBridge event -> parse -> match triggers -> dispatch executor (Lambda or ECS)
"""

from __future__ import annotations

import json
import time
from uuid import UUID

import boto3

from cogtainer.db.models import Event as BrainEvent
from cogtainer.db.models import TaskStatus, Trigger
from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.db import get_repo
from cogtainer.lambdas.shared.events import from_eventbridge, put_event
from cogtainer.lambdas.shared.logging import setup_logging

logger = setup_logging()


class TriggerCache:
    """Module-level trigger cache with TTL-based refresh."""

    def __init__(self, ttl_seconds: int = 60):
        self._triggers: list[Trigger] = []
        self._last_refresh: float = 0
        self._ttl = ttl_seconds

    def get_triggers(self) -> list[Trigger]:
        """Load enabled triggers from DB, with 60s TTL caching."""
        now = time.time()
        if now - self._last_refresh > self._ttl:
            repo = get_repo()
            self._triggers = repo.list_triggers(enabled_only=True)
            self._last_refresh = now
            logger.info(f"Refreshed trigger cache: {len(self._triggers)} enabled triggers")
        return self._triggers


# Module-level cache for warm Lambda starts
_cache = TriggerCache()


def _match_pattern(pattern: str, event_type: str) -> bool:
    """Match event type against trigger pattern. Supports * glob at end."""
    if pattern.endswith("*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


def handler(event: dict, context) -> dict:
    """Lambda entry point: parse event, match triggers, dispatch executors."""
    config = get_config()
    repo = get_repo()

    # Parse the incoming EventBridge event
    try:
        brain_event = from_eventbridge(event)
        logger.info(f"Parsed event: type={brain_event.event_type} source={brain_event.source}")
    except Exception:
        logger.exception("Failed to parse EventBridge event")
        return {"statusCode": 400, "body": "invalid_event"}

    # Log event to database (gets DB id for causal chaining)
    event_id = None
    try:
        event_id = repo.append_event(brain_event)
        logger.info(f"Event {event_id}: {brain_event.event_type} from {brain_event.source}")
    except Exception:
        logger.exception("Failed to log event to database")
        return {"statusCode": 500, "body": "event_log_failed"}

    # Handle task:run events directly — look up task, dispatch its program
    if brain_event.event_type == "task:run":
        return _handle_task_run(config, repo, brain_event, event_id)

    # Load enabled triggers (cached with 60s TTL)
    triggers = _cache.get_triggers()

    # Match triggers against event type
    matched = [t for t in triggers if _match_pattern(t.event_pattern, brain_event.event_type)]
    logger.info(f"Matched {len(matched)} triggers for event {brain_event.event_type}")

    if not matched:
        logger.info(f"No triggers matched event type {brain_event.event_type}")
        return {"statusCode": 200, "dispatched": 0, "event_id": event_id}

    # Dispatch executors for each matched trigger
    dispatched = 0
    lambda_client = boto3.client("lambda", region_name=config.region)
    ecs_client = boto3.client("ecs", region_name=config.region)

    for trigger in matched:
        try:
            # Cascade guard: don't let a program's output re-trigger itself
            if brain_event.source and brain_event.source == trigger.program_name:
                logger.info(f"Skipping cascade: {trigger.program_name} triggered by itself")
                continue

            # Throttle check
            max_events = trigger.config.max_events
            if max_events > 0:
                result = repo.throttle_check(
                    trigger.id, max_events, trigger.config.throttle_window_seconds
                )
                if not result.allowed:
                    logger.info(f"Throttled trigger {trigger.id} for {trigger.program_name}")
                    if result.state_changed:
                        put_event(
                            BrainEvent(
                                event_type="trigger:throttle:on",
                                source="orchestrator",
                                payload={"trigger_id": str(trigger.id),
                                         "program_name": trigger.program_name},
                                parent_event_id=event_id,
                            ),
                            config.event_bus_name,
                        )
                    continue
                if result.state_changed:
                    put_event(
                        BrainEvent(
                            event_type="trigger:throttle:off",
                            source="orchestrator",
                            payload={"trigger_id": str(trigger.id),
                                     "program_name": trigger.program_name},
                            parent_event_id=event_id,
                        ),
                        config.event_bus_name,
                    )

            # Session ID: caller can specify via event payload, otherwise default to program name
            session_id = (
                brain_event.payload.get("session_id")
                or f"program-{trigger.program_name}"
            )

            # Build executor payload
            payload = json.dumps(
                {
                    "trigger": {
                        "id": str(trigger.id),
                        "program_name": trigger.program_name,
                        "config": trigger.config.model_dump() if trigger.config else {},
                    },
                    "event": {
                        "id": event_id,
                        "event_type": brain_event.event_type,
                        "source": brain_event.source,
                        "payload": brain_event.payload,
                    },
                    "session_id": session_id,
                }
            )

            # Verify program exists
            program = repo.get_program(trigger.program_name)
            if not program:
                logger.warning(f"Program not found: {trigger.program_name}")
                continue

            # Determine runner: event payload override > program default > lambda
            event_payload = brain_event.payload if brain_event.payload is not None else {}
            runner = event_payload.get("runner") or program.runner or "lambda"

            if runner == "ecs":
                # Derive session_id from task for context continuity
                task_id = event_payload.get("task_id")
                clear_context = event_payload.get("clear_context", False)
                session_id = task_id if (task_id and not clear_context) else None
                _dispatch_ecs(config, ecs_client, payload, trigger.program_name,
                              session_id=session_id)
            else:
                _dispatch_lambda(config, lambda_client, payload, trigger.program_name)

            dispatched += 1

        except Exception:
            logger.exception(f"Failed to dispatch trigger {trigger.id} for program {trigger.program_name}")

    logger.info(f"Dispatched {dispatched}/{len(matched)} triggers")
    return {"statusCode": 200, "dispatched": dispatched, "event_id": event_id}


def _handle_task_run(config, repo, brain_event, event_id) -> dict:
    """Handle task:run events: look up task from DB, dispatch its program."""
    assert brain_event.payload is not None, "task:run event must have a payload"
    event_payload = brain_event.payload
    task_id = event_payload.get("task_id")
    if not task_id:
        logger.error("task:run event missing task_id in payload")
        return {"statusCode": 400, "body": "missing_task_id"}

    task = repo.get_task(UUID(task_id))
    if not task:
        logger.error(f"Task not found: {task_id}")
        return {"statusCode": 404, "body": "task_not_found"}

    program_name = task.program_name
    program = repo.get_program(program_name)
    if not program:
        logger.error(f"Program not found for task {task_id}: {program_name}")
        return {"statusCode": 404, "body": "program_not_found"}

    # Update task status to running
    task.status = TaskStatus.RUNNING
    repo.update_task(task)

    # Build executor payload with task data
    session_id = task_id if not task.clear_context else None
    payload = json.dumps({
        "trigger": {
            "id": "task-run",
            "program_name": program_name,
            "config": {},
        },
        "event": {
            "id": event_id,
            "event_type": brain_event.event_type,
            "source": brain_event.source,
            "payload": brain_event.payload,
        },
        "task": {
            "id": task_id,
            "content": task.content if task.content is not None else "",
            "memory_keys": task.memory_keys if task.memory_keys is not None else [],
            "tools": task.tools if task.tools is not None else [],
            "resources": task.resources if task.resources is not None else [],
            "clear_context": task.clear_context,
        },
        "session_id": session_id or f"program-{program_name}",
    })

    runner = task.runner or program.runner or "lambda"
    lambda_client = boto3.client("lambda", region_name=config.region)
    ecs_client = boto3.client("ecs", region_name=config.region)

    if runner == "ecs":
        _dispatch_ecs(config, ecs_client, payload, program_name, session_id=session_id)
    else:
        _dispatch_lambda(config, lambda_client, payload, program_name)

    logger.info(f"Dispatched task:run for task {task_id} -> program {program_name} via {runner}")
    return {"statusCode": 200, "dispatched": 1, "event_id": event_id, "task_id": task_id}


def _dispatch_lambda(config, lambda_client, payload: str, program_name: str):
    """Invoke executor Lambda asynchronously."""
    lambda_client.invoke(
        FunctionName=config.executor_function_name,
        InvocationType="Event",  # async invocation
        Payload=payload.encode(),
    )
    logger.info(f"Dispatched to Lambda: {program_name}")


def _dispatch_ecs(config, ecs_client, payload: str, program_name: str,
                  session_id: str | None = None):
    """Run executor as ECS Fargate task for heavy compute."""
    subnets = [s.strip() for s in config.ecs_subnets.split(",") if s.strip()]

    env_vars = [{"name": "EXECUTOR_PAYLOAD", "value": payload}]
    if session_id:
        env_vars.append({"name": "CLAUDE_CODE_SESSION", "value": session_id})

    container_overrides = {
        "name": "Executor",
        "environment": env_vars,
    }

    if config.executor_image_override:
        container_overrides["image"] = config.executor_image_override

    ecs_client.run_task(
        cluster=config.ecs_cluster_arn,
        taskDefinition=config.ecs_task_definition,
        launchType="FARGATE",
        enableExecuteCommand=True,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [config.ecs_security_group],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [container_overrides]
        },
    )
    logger.info(f"Dispatched to ECS: {program_name} (session={session_id})")

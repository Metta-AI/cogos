"""Orchestrator Lambda: receives EventBridge events, matches triggers, dispatches executors.

Flow:
  EventBridge event -> parse -> match triggers -> dispatch executor (Lambda or ECS)
"""

from __future__ import annotations

import json
import time

import boto3

from brain.db.models import Trigger
from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.db import get_repo
from brain.lambdas.shared.events import from_eventbridge
from brain.lambdas.shared.logging import setup_logging

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
                }
            )

            # Verify program exists
            program = repo.get_program(trigger.program_name)
            if not program:
                logger.warning(f"Program not found: {trigger.program_name}")
                continue

            # Dispatch to Lambda executor
            _dispatch_lambda(config, lambda_client, payload, trigger.program_name)

            dispatched += 1

        except Exception:
            logger.exception(f"Failed to dispatch trigger {trigger.id} for program {trigger.program_name}")

    logger.info(f"Dispatched {dispatched}/{len(matched)} triggers")
    return {"statusCode": 200, "dispatched": dispatched, "event_id": event_id}


def _dispatch_lambda(config, lambda_client, payload: str, program_name: str):
    """Invoke executor Lambda asynchronously."""
    lambda_client.invoke(
        FunctionName=config.executor_function_name,
        InvocationType="Event",  # async invocation
        Payload=payload.encode(),
    )
    logger.info(f"Dispatched to Lambda: {program_name}")


def _dispatch_ecs(config, ecs_client, payload: str, program_name: str):
    """Run executor as ECS Fargate task for heavy compute."""
    subnets = [s.strip() for s in config.ecs_subnets.split(",") if s.strip()]

    ecs_client.run_task(
        cluster=config.ecs_cluster_arn,
        taskDefinition=config.ecs_task_definition,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [config.ecs_security_group],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": "Executor",
                    "environment": [{"name": "EXECUTOR_PAYLOAD", "value": payload}],
                }
            ]
        },
    )
    logger.info(f"Dispatched to ECS: {program_name}")

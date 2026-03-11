"""Dispatcher Lambda: runs the CogOS scheduler tick every minute.

Matches undelivered events to handlers, selects runnable processes, and
invokes the executor for each.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point: run CogOS scheduler tick."""
    config = get_config()
    dispatched = _cogos_scheduler_tick(config)

    return {
        "statusCode": 200,
        "dispatched": dispatched,
    }


def _cogos_scheduler_tick(config) -> int:
    """CogOS scheduler tick: match events → select processes → invoke executor."""
    try:
        from cogos.db.repository import Repository
        cogos_repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping scheduler tick")
        return 0

    from uuid import UUID
    from cogos.capabilities.scheduler import SchedulerCapability

    # Use a dummy process_id for the scheduler capability
    scheduler = SchedulerCapability(cogos_repo, UUID("00000000-0000-0000-0000-000000000000"))

    # 1. Match events to handlers
    match_result = scheduler.match_events(limit=50)
    if match_result.deliveries_created > 0:
        logger.info(f"CogOS: matched {match_result.deliveries_created} event deliveries")

    # 2. Select runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return 0

    # 3. Dispatch each selected process
    lambda_client = boto3.client("lambda", region_name=config.region)
    safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
    executor_fn = f"cogent-{safe_name}-executor"

    dispatched = 0
    for proc in select_result.selected:
        dispatch_result = scheduler.dispatch_process(process_id=proc.id)
        if hasattr(dispatch_result, "error"):
            logger.warning(f"CogOS: dispatch failed for {proc.name}: {dispatch_result.error}")
            continue

        # Get the event payload for the executor
        event_payload = {}
        if dispatch_result.event_id:
            rows = cogos_repo._rows_to_dicts(cogos_repo._execute(
                "SELECT payload FROM cogos_event WHERE id = :id",
                [cogos_repo._param("id", UUID(dispatch_result.event_id))],
            ))
            if rows:
                raw = rows[0].get("payload", "{}")
                event_payload = json.loads(raw) if isinstance(raw, str) else (raw or {})

        payload = {
            "process_id": dispatch_result.process_id,
            "event_id": dispatch_result.event_id,
            "event_type": event_payload.get("event_type", ""),
            "payload": event_payload,
        }

        try:
            lambda_client.invoke(
                FunctionName=executor_fn,
                InvocationType="Event",  # async
                Payload=json.dumps(payload),
            )
            dispatched += 1
            logger.info(f"CogOS: dispatched {proc.name} (run={dispatch_result.run_id})")
        except Exception:
            logger.exception(f"CogOS: failed to invoke executor for {proc.name}")

    return dispatched

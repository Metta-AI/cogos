"""Dispatcher Lambda: runs one CogOS scheduler tick per invocation.

EventBridge fires this every 60s. Each invocation:
1. Generates virtual system:tick:minute (and system:tick:hour on the hour)
2. Matches real events to handlers
3. Selects runnable processes and dispatches executors

Virtual tick events are NOT written to the event log — they match handlers
directly and set processes to RUNNABLE.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from brain.lambdas.shared.config import get_config
from brain.lambdas.shared.logging import setup_logging

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point: single-shot scheduler tick."""
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping scheduler tick")
        return {"statusCode": 200, "dispatched": 0}

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
    executor_fn = f"cogent-{safe_name}-executor"

    # Heartbeat — lets the dashboard show time-since-last-tick
    try:
        repo.set_meta("scheduler:last_tick")
    except Exception:
        pass

    # 1. Generate virtual system tick events (not written to event log)
    _apply_system_ticks(repo)

    # 2. Match real events to handlers
    match_result = scheduler.match_events(limit=50)
    if match_result.deliveries_created > 0:
        logger.info(f"Matched {match_result.deliveries_created} event deliveries")

    # 3. Select runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return {"statusCode": 200, "dispatched": 0}

    # 4. Dispatch each selected process
    dispatched = 0
    for proc in select_result.selected:
        dispatch_result = scheduler.dispatch_process(process_id=proc.id)
        if hasattr(dispatch_result, "error"):
            logger.warning(f"Dispatch failed for {proc.name}: {dispatch_result.error}")
            continue

        event_payload = {}
        if dispatch_result.event_id:
            rows = repo._rows_to_dicts(repo._execute(
                "SELECT payload FROM cogos_event WHERE id = :id",
                [repo._param("id", UUID(dispatch_result.event_id))],
            ))
            if rows:
                raw = rows[0].get("payload", "{}")
                event_payload = json.loads(raw) if isinstance(raw, str) else (raw or {})

        payload = {
            "process_id": dispatch_result.process_id,
            "run_id": dispatch_result.run_id,
            "event_id": dispatch_result.event_id,
            "event_type": event_payload.get("event_type", ""),
            "payload": event_payload,
        }

        try:
            lambda_client.invoke(
                FunctionName=executor_fn,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )
            dispatched += 1
            logger.info(f"Dispatched {proc.name} (run={dispatch_result.run_id})")
        except Exception:
            logger.exception(f"Failed to invoke executor for {proc.name}")

    if dispatched:
        logger.info(f"Dispatcher: {dispatched} dispatched")

    return {"statusCode": 200, "dispatched": dispatched}


def _apply_system_ticks(repo) -> None:
    """Generate virtual system:tick:minute (and :hour) events.

    These match handlers and set processes to RUNNABLE but are never
    written to the cogos_event table.
    """
    from cogos.db.models import ProcessStatus

    now = datetime.now(timezone.utc)
    tick_types = ["system:tick:minute"]
    if now.minute == 0:
        tick_types.append("system:tick:hour")

    for tick_type in tick_types:
        handlers = repo.match_handlers(tick_type)
        for h in handlers:
            proc = repo.get_process(h.process)
            if proc and proc.status == ProcessStatus.WAITING:
                repo.update_process_status(h.process, ProcessStatus.RUNNABLE)
                logger.info(f"System tick {tick_type} -> {proc.name} RUNNABLE")

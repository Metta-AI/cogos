"""Dispatcher Lambda: runs one CogOS scheduler tick per invocation.

EventBridge fires this every 60s. Each invocation:
1. Generates virtual system:tick:minute (and system:tick:hour on the hour)
2. Matches channel messages to handlers
3. Selects any remaining runnable processes and dispatches executors

Virtual tick events are emitted as channel messages and wake handlers via deliveries.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.logging import setup_logging
from cogos.runtime.ingress import dispatch_ready_processes
from cogos.runtime.schedule import apply_scheduled_messages

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
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    # Heartbeat — lets the dashboard show time-since-last-tick
    try:
        repo.set_meta("scheduler:last_tick")
        repo.set_meta("state:modified_at")
    except Exception:
        pass

    # 0a. Reap runs stuck in RUNNING longer than 15 minutes (Lambda max timeout)
    reaped = repo.timeout_stale_runs(max_age_ms=900_000)
    if reaped:
        logger.warning("Reaped %s stale runs stuck in RUNNING state", reaped)

    # 0b. Recover stuck daemons — if RUNNING but no active run, reset to WAITING
    _recover_stuck_daemons(repo)

    # 1. Generate virtual system tick events (not written to event log)
    _apply_system_ticks(repo)

    # 2. Match channel messages to handlers
    dispatched = 0
    match_result = scheduler.match_messages()
    if match_result.deliveries_created > 0:
        logger.info("Matched %s message deliveries", match_result.deliveries_created)
        dispatched += dispatch_ready_processes(
            repo,
            scheduler,
            lambda_client,
            executor_fn,
            {UUID(info.process_id) for info in match_result.deliveries},
        )

    # 3. Select any remaining runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return {"statusCode": 200, "dispatched": dispatched}

    # 4. Dispatch each selected process
    for proc in select_result.selected:
        try:
            dispatched += dispatch_ready_processes(
                repo,
                scheduler,
                lambda_client,
                executor_fn,
                {UUID(proc.id)},
            )
        except Exception:
            logger.exception("Failed to invoke executor for %s", proc.name)

    if dispatched:
        logger.info("Dispatcher: %s dispatched", dispatched)

    return {"statusCode": 200, "dispatched": dispatched}


def _recover_stuck_daemons(repo) -> None:
    """Reset daemon processes stuck in RUNNING with no active run."""
    from cogos.db.models import ProcessMode, ProcessStatus, RunStatus

    running = repo.list_processes(status=ProcessStatus.RUNNING)
    for proc in running:
        if proc.mode != ProcessMode.DAEMON:
            continue
        runs = repo.list_runs(process_id=proc.id, limit=1)
        if not runs or runs[0].status != RunStatus.RUNNING:
            repo.update_process_status(proc.id, ProcessStatus.WAITING)
            logger.info("Recovered stuck daemon %s: running -> waiting", proc.name)
            try:
                repo.create_alert(
                    severity="warning",
                    alert_type="scheduler:stuck_daemon",
                    source="dispatcher",
                    message=f"Recovered stuck daemon '{proc.name}': was running with no active run, reset to waiting",
                    metadata={"process_id": str(proc.id), "process_name": proc.name},
                )
            except Exception:
                logger.debug("Could not create alert for stuck daemon %s", proc.name)




def _apply_system_ticks(repo, *, now: datetime | None = None) -> None:
    """Generate virtual system:tick:minute (and :hour) events.

    These now flow through the shared channel scheduler path so both
    local and prod dispatch wake handlers the same way.
    """
    apply_scheduled_messages(repo, now=now or datetime.now(timezone.utc))

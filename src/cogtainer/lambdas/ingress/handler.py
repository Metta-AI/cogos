"""Immediate CogOS ingress: select and dispatch runnable processes.

When invoked via SQS with a ``process_id`` field the nudged process is
dispatched directly, bypassing weighted selection so that low-priority
processes are not starved by higher-priority ones.
"""

from __future__ import annotations

import json
import os
from uuid import UUID

import boto3

from cogos.runtime.ingress import dispatch_ready_processes
from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.logging import setup_logging
from cogtainer.runtime.factory import create_executor_runtime

logger = setup_logging()


def _extract_process_ids(event: dict) -> set[UUID]:
    """Return process IDs explicitly requested in the SQS event."""
    pids: set[UUID] = set()
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        pid_str = body.get("process_id")
        if pid_str:
            try:
                pids.add(UUID(pid_str))
            except ValueError:
                logger.warning("Invalid process_id in ingress event: %s", pid_str)
    # Also support direct invocation (non-SQS) with a top-level process_id
    top_pid = event.get("process_id")
    if top_pid:
        try:
            pids.add(UUID(top_pid))
        except ValueError:
            pass
    return pids


def handler(event: dict, context) -> dict:
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    cogent_name = os.environ["COGENT"]
    runtime = create_executor_runtime()
    repo = runtime.get_repository(cogent_name)

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ["COGENT"].replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    try:
        repo.set_meta("scheduler:last_ingress")
    except Exception:
        pass

    dispatched = 0

    # 1. Dispatch explicitly-nudged processes first (bypasses priority selection)
    nudged_pids = _extract_process_ids(event)
    if nudged_pids:
        dispatched += dispatch_ready_processes(
            repo, scheduler, lambda_client, executor_fn, nudged_pids,
        )

    # 2. Also select and dispatch other runnable processes via weighted selection
    select_result = scheduler.select_processes(slots=5)
    if select_result.selected:
        # Exclude already-dispatched nudged processes
        remaining = {UUID(proc.id) for proc in select_result.selected} - nudged_pids
        if remaining:
            dispatched += dispatch_ready_processes(
                repo, scheduler, lambda_client, executor_fn, remaining,
            )

    if dispatched:
        logger.info("Ingress dispatched %s processes (nudged=%s)", dispatched, len(nudged_pids))

    return {
        "statusCode": 200,
        "dispatched": dispatched,
    }

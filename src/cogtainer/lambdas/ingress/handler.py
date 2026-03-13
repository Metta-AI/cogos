"""Immediate CogOS ingress: drain the event outbox and dispatch runnable work."""

from __future__ import annotations

import os
from uuid import UUID

import boto3

from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.logging import setup_logging
from cogos.runtime.ingress import dispatch_ready_processes

logger = setup_logging()


def handler(event: dict, context) -> dict:
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping ingress wake")
        return {"statusCode": 200, "dispatched": 0, "outbox_rows": 0}

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    try:
        repo.set_meta("scheduler:last_ingress")
    except Exception:
        pass

    # Select and dispatch any runnable processes (channel messages already
    # create deliveries and mark processes RUNNABLE in append_channel_message)
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return {"statusCode": 200, "dispatched": 0}

    dispatched = dispatch_ready_processes(
        repo,
        scheduler,
        lambda_client,
        executor_fn,
        {UUID(proc.id) for proc in select_result.selected},
    )

    if dispatched:
        logger.info("Ingress dispatched %s processes", dispatched)

    return {
        "statusCode": 200,
        "dispatched": dispatched,
    }

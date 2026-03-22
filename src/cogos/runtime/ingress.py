"""Shared dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

from cogos.db.models import ProcessStatus
from cogos.runtime.dispatch import build_dispatch_event

logger = logging.getLogger(__name__)


def dispatch_single_process(
    repo,
    process,
    dispatch_result,
    lambda_client: Any,
    ecs_client: Any,
    executor_function_name: str,
    ecs_cluster: str,
    ecs_task_definition: str,
) -> bool:
    payload = build_dispatch_event(repo, dispatch_result)

    try:
        if process.runner == "ecs":
            ecs_client.run_task(
                cluster=ecs_cluster,
                taskDefinition=ecs_task_definition,
                launchType="FARGATE",
                overrides={
                    "containerOverrides": [{
                        "name": "agent-executor",
                        "environment": [
                            {"name": "DISPATCH_EVENT", "value": json.dumps(payload)},
                        ],
                    }],
                },
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": os.environ.get("ECS_SUBNETS", "").split(","),
                        "securityGroups": os.environ.get("ECS_SECURITY_GROUPS", "").split(","),
                        "assignPublicIp": "DISABLED",
                    }
                },
                capacityProviderStrategy=[
                    {"capacityProvider": "FARGATE_SPOT", "weight": 1},
                ],
            )
        else:
            response = lambda_client.invoke(
                FunctionName=executor_function_name,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )
            if response.get("StatusCode") != 202:
                raise RuntimeError(f"unexpected lambda invoke status {response.get('StatusCode')}")
        return True
    except Exception as exc:
        repo.rollback_dispatch(
            process.id,
            UUID(dispatch_result.run_id),
            UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
            error=str(exc),
        )
        logger.exception("Failed to invoke executor for process %s", process.id)
        return False


def dispatch_ready_processes(
    repo,
    scheduler,
    lambda_client: Any,
    executor_function_name: str,
    process_ids: set[UUID],
    ecs_client: Any = None,
    ecs_cluster: str = "",
    ecs_task_definition: str = "",
) -> int:
    dispatched = 0

    for process_id in sorted(process_ids, key=str):
        proc = repo.get_process(process_id)
        if proc is None or proc.status != ProcessStatus.RUNNABLE:
            continue

        # Route channel-runner processes to channel dispatch
        if proc.runner == "channel":
            result = scheduler.dispatch_channel(process_id=str(process_id))
            if hasattr(result, "error"):
                logger.warning("Channel dispatch failed for %s: %s", process_id, result.error)
            else:
                logger.info(
                    "Dispatched %s to channel executor %s (run %s)",
                    proc.name, result.executor_id, result.run_id,
                )
                dispatched += 1
            continue

        dispatch_result = scheduler.dispatch_process(process_id=str(process_id))
        if hasattr(dispatch_result, "error"):
            logger.warning("Dispatch failed for %s: %s", process_id, dispatch_result.error)
            continue

        if dispatch_single_process(
            repo=repo,
            process=proc,
            dispatch_result=dispatch_result,
            lambda_client=lambda_client,
            ecs_client=ecs_client,
            executor_function_name=executor_function_name,
            ecs_cluster=ecs_cluster,
            ecs_task_definition=ecs_task_definition,
        ):
            dispatched += 1

    return dispatched

"""Shared dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from cogos.db.models import ChannelMessage, ProcessStatus
from cogos.runtime.dispatch import build_dispatch_event

logger = logging.getLogger(__name__)


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

        result = scheduler.dispatch_to_executor(process_id=str(process_id))
        if hasattr(result, "error"):
            logger.warning("Executor dispatch failed for %s: %s", process_id, result.error)
            continue

        executor = repo.get_executor(result.executor_id)
        if not executor:
            logger.error("Executor %s not found after dispatch", result.executor_id)
            continue

        payload = build_dispatch_event(repo, result)

        if executor.dispatch_type == "lambda":
            try:
                response = lambda_client.invoke(
                    FunctionName=executor_function_name,
                    InvocationType="Event",
                    Payload=json.dumps(payload),
                )
                if response.get("StatusCode") != 202:
                    raise RuntimeError(f"unexpected status {response.get('StatusCode')}")
                dispatched += 1
            except Exception as exc:
                repo.rollback_dispatch(
                    proc.id, UUID(result.run_id),
                    UUID(result.delivery_id) if getattr(result, "delivery_id", None) else None,
                    error=str(exc),
                )
                logger.exception("Failed to invoke lambda for %s", proc.name)
        else:
            # Channel dispatch: send work to executor's channel
            exec_ch = repo.get_channel_by_name(f"system:executor:{result.executor_id}")
            if exec_ch:
                repo.append_channel_message(ChannelMessage(
                    channel=exec_ch.id,
                    payload=payload,
                ))
                logger.info(
                    "Dispatched %s to channel executor %s (run %s)",
                    proc.name, result.executor_id, result.run_id,
                )
                dispatched += 1
            else:
                logger.error("Executor channel not found for %s", result.executor_id)
                repo.rollback_dispatch(
                    proc.id, UUID(result.run_id), None,
                    error="executor channel not found",
                )

    return dispatched

"""Shared dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from cogos.db.models import ProcessStatus

logger = logging.getLogger(__name__)


def dispatch_ready_processes(
    repo,
    scheduler,
    lambda_client: Any,
    executor_function_name: str,
    process_ids: set[UUID],
) -> int:
    dispatched = 0

    for process_id in sorted(process_ids, key=str):
        proc = repo.get_process(process_id)
        if proc is None or proc.status != ProcessStatus.RUNNABLE:
            continue

        dispatch_result = scheduler.dispatch_process(process_id=str(process_id))
        if hasattr(dispatch_result, "error"):
            logger.warning("Dispatch failed for %s: %s", process_id, dispatch_result.error)
            continue

        message_payload: dict[str, Any] = {}
        if dispatch_result.message_id:
            msg_id = UUID(dispatch_result.message_id)
            # Try channel message lookup
            for ch_msg in getattr(repo, '_channel_messages', {}).values():
                if ch_msg.id == msg_id:
                    message_payload = ch_msg.payload or {}
                    break
            else:
                # RDS path: query by message ID
                try:
                    rows = repo.query(
                        "SELECT payload FROM cogos_channel_message WHERE id = :id",
                        {"id": msg_id},
                    )
                    if rows:
                        message_payload = repo._json_field(rows[0], "payload", {})
                except Exception:
                    pass

        payload = {
            "process_id": dispatch_result.process_id,
            "run_id": dispatch_result.run_id,
            "message_id": dispatch_result.message_id,
            "payload": message_payload,
        }

        try:
            response = lambda_client.invoke(
                FunctionName=executor_function_name,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )
            if response.get("StatusCode") != 202:
                raise RuntimeError(f"unexpected lambda invoke status {response.get('StatusCode')}")
            dispatched += 1
        except Exception as exc:
            repo.rollback_dispatch(
                process_id,
                UUID(dispatch_result.run_id),
                UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
                error=str(exc),
            )
            logger.exception("Failed to invoke executor for process %s", process_id)

    return dispatched

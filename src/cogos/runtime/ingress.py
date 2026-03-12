"""Shared immediate-ingress and backstop dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from cogos.db.models import ProcessStatus

logger = logging.getLogger(__name__)


@dataclass
class DrainResult:
    outbox_rows: int = 0
    deliveries_created: int = 0
    affected_processes: set[UUID] = field(default_factory=set)
    failures: int = 0


def drain_outbox(repo, scheduler, *, batch_size: int = 25, max_batches: int = 20) -> DrainResult:
    result = DrainResult()

    for _ in range(max_batches):
        batch = repo.claim_event_outbox_batch(limit=batch_size)
        if not batch:
            break

        result.outbox_rows += len(batch)
        events = repo.get_events_by_ids([item.event for item in batch])

        for item in batch:
            event = events.get(item.event)
            if event is None:
                repo.mark_event_outbox_failed(item.id, f"missing event row {item.event}")
                result.failures += 1
                continue

            try:
                deliveries = scheduler.deliver_event(event)
                result.deliveries_created += len(deliveries)
                result.affected_processes.update(UUID(info.process_id) for info in deliveries)
                repo.mark_event_outbox_done(item.id)
            except Exception as exc:
                logger.exception("Failed to process event outbox row %s", item.id)
                repo.mark_event_outbox_failed(item.id, str(exc))
                result.failures += 1

    return result


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

        event_payload: dict[str, Any] = {}
        event_type = ""
        if dispatch_result.event_id:
            # event_id now points to a channel message ID
            msg_id = UUID(dispatch_result.event_id)
            # Try channel message lookup
            for ch_msg in getattr(repo, '_channel_messages', {}).values():
                if ch_msg.id == msg_id:
                    event_payload = ch_msg.payload or {}
                    event_type = event_payload.get("event_type", "")
                    break
            else:
                # RDS path: query by message ID
                try:
                    rows = repo.query(
                        "SELECT payload FROM cogos_channel_message WHERE id = :id",
                        {"id": msg_id},
                    )
                    if rows:
                        event_payload = repo._json_field(rows[0], "payload", {})
                        event_type = event_payload.get("event_type", "")
                except Exception:
                    pass

        payload = {
            "process_id": dispatch_result.process_id,
            "run_id": dispatch_result.run_id,
            "event_id": dispatch_result.event_id,
            "event_type": event_type or event_payload.get("event_type", ""),
            "payload": event_payload,
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

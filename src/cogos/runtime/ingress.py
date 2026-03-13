"""Shared dispatch helpers for CogOS."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from cogos.executor.session_store import SessionStore
from cogos.db.models import ProcessStatus
from cogos.runtime.dispatch import build_dispatch_event

logger = logging.getLogger(__name__)


def _persist_dispatch_failure_artifacts(
    repo,
    process,
    event_data: dict[str, Any],
    run_id: UUID,
    *,
    error: str,
    executor_function_name: str,
) -> dict[str, Any] | None:
    session_store = SessionStore(repo)

    try:
        session = session_store.resolve_session(process, event_data, run_id)
        checkpoint_key = session.checkpoint_key if session.resume_enabled else None
        session_store.write_manifest(
            session,
            latest_run_id=run_id,
            checkpoint_key=checkpoint_key,
        )
        session_store.write_trigger(
            session,
            event_data=event_data,
            user_message={
                "role": "user",
                "content": [{"text": "Executor dispatch failed before the run started."}],
            },
        )
        session_store.write_step(
            session,
            seq=1,
            step_type="dispatch_failed",
            payload={
                "status": "failed",
                "final_stop_reason": "dispatch_error",
                "error": error[:4000],
                "executor_function_name": executor_function_name,
                "message_id": event_data.get("message_id"),
                "payload": event_data.get("payload"),
            },
        )
        return session_store.finalize_run(
            session,
            status="failed",
            resumed=False,
            resumed_from_run_id=None,
            resume_skipped_reason="executor_not_started",
            final_stop_reason="dispatch_error",
            error=error[:4000],
            last_completed_step=1,
            message_count=1,
            checkpoint_key=checkpoint_key,
        )
    except Exception:
        logger.exception("Failed to persist dispatch failure artifacts for run %s", run_id)
        return None


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

        payload = build_dispatch_event(repo, dispatch_result)

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
            snapshot = _persist_dispatch_failure_artifacts(
                repo,
                proc,
                payload,
                UUID(dispatch_result.run_id),
                error=str(exc),
                executor_function_name=executor_function_name,
            )
            repo.rollback_dispatch(
                process_id,
                UUID(dispatch_result.run_id),
                UUID(dispatch_result.delivery_id) if dispatch_result.delivery_id else None,
                error=str(exc),
                snapshot=snapshot,
            )
            logger.exception("Failed to invoke executor for process %s", process_id)

    return dispatched

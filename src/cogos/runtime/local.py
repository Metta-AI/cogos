"""Local executor helpers for running processes in-process."""

from __future__ import annotations

import time
from typing import Any, Callable

from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    ProcessStatus,
    Run,
    RunStatus,
)


def _emit_lifecycle(repo, process, payload: dict) -> None:
    """Publish a lifecycle message to the process's implicit channel (process:<name>)."""
    ch_name = f"process:{process.name}"
    ch = repo.get_channel_by_name(ch_name)
    if not ch:
        ch = Channel(
            name=ch_name,
            owner_process=process.id,
            channel_type=ChannelType.IMPLICIT,
        )
        repo.upsert_channel(ch)
    repo.append_channel_message(
        ChannelMessage(channel=ch.id, sender_process=process.id, payload=payload)
    )


def run_and_complete(
    process,
    event_data: dict,
    run: Run,
    config,
    repo,
    *,
    execute_fn: Callable | None = None,
    bedrock_client: Any | None = None,
) -> Run:
    """Execute a process run and handle completion / failure lifecycle.

    1. Mark queued deliveries as delivered for this run.
    2. Call *execute_fn* (defaults to ``cogos.executor.handler.execute_process``).
    3. On success – complete the run, emit a lifecycle event, transition the
       process state (daemon -> WAITING/RUNNABLE, one_shot -> COMPLETED).
    4. On failure – complete the run as FAILED, emit a lifecycle event,
       transition (daemon -> WAITING/RUNNABLE, one_shot with retries ->
       RUNNABLE + increment, one_shot exhausted -> DISABLED).
    5. Return the *run* object in both cases.
    """
    if execute_fn is None:
        from cogos.executor.handler import execute_process

        execute_fn = execute_process

    repo.mark_run_deliveries_delivered(run.id)

    start = time.time()
    try:
        run = execute_fn(process, event_data, run, config, repo, bedrock_client=bedrock_client)
        duration_ms = int((time.time() - start) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.COMPLETED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            result=run.result,
            scope_log=run.scope_log,
        )

        _emit_lifecycle(repo, process, {
            "status": "success",
            "run_id": str(run.id),
            "process_name": process.name,
            "duration_ms": duration_ms,
        })

        # Transition process state
        if process.mode.value == "daemon":
            next_status = (
                ProcessStatus.RUNNABLE
                if repo.has_pending_deliveries(process.id)
                else ProcessStatus.WAITING
            )
            repo.update_process_status(process.id, next_status)
        else:
            repo.update_process_status(process.id, ProcessStatus.COMPLETED)

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.FAILED,
            duration_ms=duration_ms,
            error=str(e)[:4000],
        )

        _emit_lifecycle(repo, process, {
            "status": "failed",
            "run_id": str(run.id),
            "process_name": process.name,
            "error": str(e)[:1000],
        })

        # Transition process state
        if process.mode.value == "daemon":
            next_status = (
                ProcessStatus.RUNNABLE
                if repo.has_pending_deliveries(process.id)
                else ProcessStatus.WAITING
            )
            repo.update_process_status(process.id, next_status)
        elif process.retry_count < process.max_retries:
            repo.increment_retry(process.id)
            repo.update_process_status(process.id, ProcessStatus.RUNNABLE)
        else:
            repo.update_process_status(process.id, ProcessStatus.DISABLED)

    return run

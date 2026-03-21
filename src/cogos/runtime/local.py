"""Local executor helpers for running processes in-process."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable
from uuid import UUID

from cogos.capabilities.scheduler import SchedulerCapability, SchedulerError
from cogos.db.models import (
    Channel,
    ChannelMessage,
    ChannelType,
    ProcessStatus,
    Run,
    RunStatus,
)
from cogos.runtime.dispatch import build_dispatch_event
from cogos.runtime.schedule import apply_scheduled_messages

logger = logging.getLogger(__name__)

_SENTINEL_UUID = UUID("00000000-0000-0000-0000-000000000000")


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
        run = execute_fn(process, event_data, run, config, repo)
        duration_ms = int((time.time() - start) * 1000)

        repo.complete_run(
            run.id,
            status=RunStatus.COMPLETED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            result=run.result,
            snapshot=run.snapshot,
            scope_log=run.scope_log,
        )

        _emit_lifecycle(repo, process, {
            "type": "process:run:success",
            "run_id": str(run.id),
            "process_id": str(process.id),
            "process_name": process.name,
            "duration_ms": duration_ms,
        })

        from cogos.executor.handler import _notify_parent_on_exit
        _notify_parent_on_exit(repo, process, run, exit_code=0, duration_ms=duration_ms)

        # Transition process state — respect out-of-band status changes
        current = repo.get_process(process.id)
        if current and current.status not in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
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
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            error=str(e)[:4000],
            snapshot=run.snapshot,
        )

        _emit_lifecycle(repo, process, {
            "type": "process:run:failed",
            "run_id": str(run.id),
            "process_id": str(process.id),
            "process_name": process.name,
            "error": str(e)[:1000],
        })

        try:
            repo.create_alert(
                severity="warning",
                alert_type="process:run:failed",
                source="local_executor",
                message=f"Run failed for '{process.name}': {str(e)[:500]}",
                metadata={
                    "process_id": str(process.id),
                    "process_name": process.name,
                    "run_id": str(run.id),
                    "duration_ms": duration_ms,
                },
            )
        except Exception:
            logger.debug("Could not create alert for failed run %s", run.id)

        from cogos.executor.handler import _notify_parent_on_exit
        _notify_parent_on_exit(repo, process, run, exit_code=1, duration_ms=duration_ms, error=str(e))

        # Retry logic — respect out-of-band status changes
        current = repo.get_process(process.id)
        if current and current.status in (ProcessStatus.DISABLED, ProcessStatus.SUSPENDED):
            pass
        elif process.mode.value == "daemon":
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


def run_local_tick(
    repo,
    config,
    *,
    execute_fn: Callable | None = None,
    now: datetime | None = None,
) -> int:
    """Run one tick of the local executor loop.

    Returns the number of processes executed.
    """
    scheduler = SchedulerCapability(repo, process_id=_SENTINEL_UUID)

    apply_scheduled_messages(repo, now=now)

    # Backstop: ensure all channel messages have deliveries
    scheduler.match_messages()

    # Reap idle daemon processes
    scheduler.reap_idle_processes()

    executed = 0
    while True:
        selection = scheduler.select_processes(slots=1)
        if not selection.selected:
            break

        proc_info = selection.selected[0]
        dispatch = scheduler.dispatch_process(proc_info.id)

        if isinstance(dispatch, SchedulerError):
            logger.warning("dispatch error for %s: %s", proc_info.id, dispatch.error)
            break

        process = repo.get_process(UUID(dispatch.process_id))
        run = repo.get_run(UUID(dispatch.run_id))
        event_data = build_dispatch_event(repo, dispatch)

        run_and_complete(
            process,
            event_data,
            run,
            config,
            repo,
            execute_fn=execute_fn,
        )
        executed += 1

    return executed


def run_local_loop(
    repo,
    config,
    *,
    poll_interval: float = 2.0,
    once: bool = False,
) -> None:
    """Simple daemon wrapper that repeatedly calls run_local_tick."""
    logger.info("run_local_loop starting (poll_interval=%.1fs, once=%s)", poll_interval, once)

    while True:
        try:
            executed = run_local_tick(repo, config)
            if executed > 0:
                logger.info("run_local_tick executed %d process(es)", executed)
        except Exception:
            logger.exception("run_local_tick error")

        if once:
            break

        time.sleep(poll_interval)

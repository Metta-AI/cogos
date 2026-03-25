"""Dispatcher Lambda: runs one CogOS scheduler tick per invocation.

EventBridge fires this every 60s. Each invocation:
1. Generates virtual system:tick:minute (and system:tick:hour on the hour)
2. Matches channel messages to handlers
3. Unblocks BLOCKED processes whose resources are now available
4. Selects any remaining runnable processes and dispatches executors

Virtual tick events are emitted as channel messages and wake handlers via deliveries.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from cogos.runtime.ingress import dispatch_ready_processes
from cogos.runtime.schedule import apply_scheduled_messages
from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.logging import setup_logging
from cogtainer.runtime.factory import create_executor_runtime

logger = setup_logging()

_THROTTLE_COOLDOWN_MS = 300_000  # 5 minutes


def _is_throttle_cooldown_active(repo) -> bool:
    """Check if any recent run was throttled, indicating we should back off."""
    from cogos.db.models import RunStatus
    recent = repo.list_recent_failed_runs(max_age_ms=_THROTTLE_COOLDOWN_MS)
    return any(r.status == RunStatus.THROTTLED for r in recent)


def _run_migrations_once(repo) -> None:
    """Apply CogOS SQL migrations on first invocation (cold start)."""
    if getattr(_run_migrations_once, "_done", False):
        return
    try:
        from cogos.db.migrations import apply_cogos_sql_migrations
        apply_cogos_sql_migrations(repo, on_error=lambda f, e: logger.debug("migration %s: %s", f, e))
    except Exception:
        logger.debug("CogOS SQL migrations failed", exc_info=True)
    _run_migrations_once._done = True


def handler(event: dict, context) -> dict:
    """Lambda entry point: single-shot scheduler tick."""
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    cogent_name = os.environ["COGENT"]
    runtime = create_executor_runtime()
    repo = runtime.get_repository(cogent_name)

    _run_migrations_once(repo)

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ["COGENT"].replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    # Ensure a lambda pool executor is registered for processes requiring "lambda" tag
    from cogos.db.models.executor import Executor
    lambda_executor = Executor(
        executor_id="lambda-pool",
        channel_type="lambda",
        executor_tags=["lambda", "python"],
        dispatch_type="lambda",
        metadata={"pool": True},
    )
    repo.register_executor(lambda_executor)

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

    # 0b. Recover stuck processes — run finished but process still WAITING
    _recover_stuck_processes(repo)

    # 0b2. Wake waiting daemons that have pending deliveries
    _wake_waiting_with_pending(repo)

    # 0c. Flush failed runs to dead-letter channel
    flushed = _flush_dead_letters(repo)
    if flushed:
        logger.info("Flushed %s failed runs to dead-letter channel", flushed)

    # 0d. Check throttle cooldown — skip LLM dispatch but allow maintenance above
    throttle_active = _is_throttle_cooldown_active(repo)
    if throttle_active:
        logger.info("Throttle cooldown active — skipping LLM dispatch this tick")
        return {"statusCode": 200, "dispatched": 0, "throttle_cooldown": True}

    # 1. Generate virtual system tick events (not written to event log)
    _apply_system_ticks(repo)

    # 1b. Unblock processes that were blocked due to executor unavailability
    try:
        scheduler.unblock_processes()
    except Exception:
        logger.warning("Unblock processes failed", exc_info=True)

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

    # 2b. Unblock BLOCKED processes whose resources are now available
    unblock_result = scheduler.unblock_processes()
    if unblock_result.unblocked:
        logger.info("Unblocked %s processes", len(unblock_result.unblocked))

    # 3. Select and dispatch ALL remaining runnable processes.
    #    Each executor runs in its own Lambda invocation so there is no
    #    reason to limit slots — starving low-priority processes causes
    #    multi-minute scheduling delays for interactive workloads like DMs.
    select_result = scheduler.select_processes(slots=50)
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


def _recover_stuck_processes(repo) -> None:
    """Recover processes with stale RUNNING runs (executor crash recovery).

    Finds runs stuck in RUNNING state whose process has no active executor,
    fails the run, and transitions the process appropriately.
    """
    from cogos.db.models import ProcessMode, ProcessStatus, RunStatus

    waiting = repo.list_processes(status=ProcessStatus.WAITING)
    for proc in waiting:
        runs = repo.list_runs(process_id=proc.id, limit=1)
        if not runs or runs[0].status == RunStatus.RUNNING:
            continue  # no runs yet, or actively executing
        # Latest run finished but process is still WAITING — may be stuck
        if proc.mode == ProcessMode.DAEMON:
            if repo.has_pending_deliveries(proc.id):
                repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
                logger.info("Recovered stuck daemon %s: waiting -> runnable (has pending deliveries)", proc.name)
            # else: legitimately waiting, leave it
        else:
            repo.update_process_status(proc.id, ProcessStatus.DISABLED)
            logger.info("Recovered stuck one-shot %s: waiting -> disabled (run finished)", proc.name)
            try:
                repo.create_alert(
                    severity="warning",
                    alert_type="scheduler:stuck_process",
                    source="dispatcher",
                    message=f"Recovered stuck one-shot '{proc.name}': run finished but process was still waiting",
                    metadata={"process_id": str(proc.id), "process_name": proc.name},
                )
            except Exception:
                logger.debug("Could not create alert for stuck process %s", proc.name)


def _wake_waiting_with_pending(repo) -> None:
    """Transition WAITING daemons with pending deliveries to RUNNABLE."""
    from cogos.db.models import ProcessMode, ProcessStatus

    waiting = repo.list_processes(status=ProcessStatus.WAITING)
    for proc in waiting:
        if proc.mode != ProcessMode.DAEMON:
            continue
        if repo.has_pending_deliveries(proc.id):
            repo.update_process_status(proc.id, ProcessStatus.RUNNABLE)
            logger.info("Woke waiting daemon %s: has pending deliveries", proc.name)




def _flush_dead_letters(repo) -> int:
    """Write recently failed/timed-out runs to the dead-letter channel for visibility."""
    from cogos.db.models import Channel, ChannelMessage, ChannelType

    # Ensure the dead-letter channel exists
    dl_ch = repo.get_channel_by_name("system:dead-letter")
    if dl_ch is None:
        dl_ch = Channel(name="system:dead-letter", channel_type=ChannelType.NAMED)
        repo.upsert_channel(dl_ch)
        dl_ch = repo.get_channel_by_name("system:dead-letter")

    # Find runs that failed or timed out in the last 2 minutes
    # (dispatcher runs every 60s, so 2min catches anything since last tick)
    failed_runs = repo.list_recent_failed_runs(max_age_ms=120_000)
    flushed = 0
    for run in failed_runs:
        # Skip if already reported (check metadata)
        if run.metadata and run.metadata.get("dead_letter_reported"):
            continue

        process = repo.get_process(run.process)
        process_name = process.name if process else str(run.process)

        repo.append_channel_message(ChannelMessage(
            channel=dl_ch.id,
            payload={
                "type": "executor:failed",
                "run_id": str(run.id),
                "process_id": str(run.process),
                "process_name": process_name,
                "status": run.status.value,
                "error": run.error or "unknown",
                "duration_ms": run.duration_ms,
            },
        ))

        # Mark as reported to avoid duplicate dead-letters
        run_meta = run.metadata or {}
        run_meta["dead_letter_reported"] = True
        try:
            repo.update_run_metadata(run.id, run_meta)
        except Exception:
            logger.warning(
                "Failed to persist dead-letter metadata for run %s; continuing",
                run.id,
                exc_info=True,
            )
        flushed += 1

    return flushed


def _apply_system_ticks(repo, *, now: datetime | None = None) -> None:
    """Generate virtual system:tick:minute (and :hour) events.

    These now flow through the shared channel scheduler path so both
    local and prod dispatch wake handlers the same way.
    """
    apply_scheduled_messages(repo, now=now or datetime.now(timezone.utc))

"""Local dispatcher — tick + event-driven process scheduling for local runtime.

Mirrors the Lambda dispatcher handler but runs as a long-lived loop,
dispatching via CogtainerRuntime.spawn_executor instead of Lambda invoke.

Between full scheduler ticks the loop also drains the local ingress queue
(an in-memory SQS mock) so that channel-message nudges trigger near-instant
dispatch — matching production behaviour where SQS wakes the ingress Lambda.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_THROTTLE_COOLDOWN_MS = 300_000  # 5 minutes
_DEFAULT_TICK_INTERVAL = 60  # seconds
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _is_throttle_cooldown_active(repo: Any) -> bool:
    """Check if any recent run was throttled, indicating we should back off."""
    from cogos.db.models import RunStatus

    recent = repo.list_recent_failed_runs(max_age_ms=_THROTTLE_COOLDOWN_MS)
    return any(r.status == RunStatus.THROTTLED for r in recent)


def run_tick(repo: Any, runtime: Any, cogent_name: str) -> dict:
    """Single scheduler tick. Returns {"dispatched": int}."""
    from cogos.capabilities.scheduler import SchedulerCapability
    from cogos.runtime.schedule import apply_scheduled_messages

    if hasattr(repo, "_load"):
        repo._load()

    scheduler = SchedulerCapability(repo, _NULL_UUID)
    dispatched = 0

    # 1. Heartbeat
    try:
        repo.set_meta("scheduler:last_tick")
        repo.set_meta("state:modified_at")
        # Heartbeat the local-daemon executor
        from cogos.db.models import ExecutorStatus
        repo.heartbeat_executor("local-daemon", status=ExecutorStatus.IDLE)
    except Exception:
        logger.warning("Heartbeat failed", exc_info=True)

    # 2a. Reap dead executor subprocesses
    try:
        if hasattr(runtime, "reap_dead_executors"):
            dead = runtime.reap_dead_executors(repo)
            if dead:
                logger.warning("Failed %s runs from dead executor subprocesses", dead)
    except Exception:
        logger.warning("Reap dead executors failed", exc_info=True)

    # 2b. Reap stale runs (15-minute timeout)
    try:
        reaped = repo.timeout_stale_runs(max_age_ms=900_000)
        if reaped:
            logger.warning("Reaped %s stale runs", reaped)
    except Exception:
        logger.warning("Reap stale runs failed", exc_info=True)

    # 3. Throttle check
    try:
        if _is_throttle_cooldown_active(repo):
            logger.info("Throttle cooldown active — skipping dispatch")
            return {"dispatched": 0, "throttle_cooldown": True}
    except Exception:
        logger.warning("Throttle check failed", exc_info=True)

    # 4. System ticks
    try:
        apply_scheduled_messages(repo, now=datetime.now(timezone.utc))
    except Exception:
        logger.warning("System ticks failed", exc_info=True)

    # 5. Match messages
    try:
        match_result = scheduler.match_messages()
        if match_result.deliveries_created > 0:
            logger.info("Matched %s message deliveries", match_result.deliveries_created)
    except Exception:
        logger.warning("Match messages failed", exc_info=True)

    # 6. Select processes
    try:
        select_result = scheduler.select_processes(slots=50)
    except Exception:
        logger.warning("Select processes failed", exc_info=True)
        return {"dispatched": dispatched}

    # 7. Dispatch via runtime.spawn_executor
    if select_result.selected:
        for proc in select_result.selected:
            try:
                dispatch_result = scheduler.dispatch_process(process_id=proc.id)
                if hasattr(dispatch_result, "error"):
                    logger.warning("Dispatch failed for %s: %s", proc.name, getattr(dispatch_result, "error", ""))
                    continue
                runtime.spawn_executor(cogent_name, proc.id)
                dispatched += 1
            except Exception:
                logger.exception("Failed to dispatch process %s", proc.name)

    if dispatched:
        logger.info("Tick dispatched %s processes", dispatched)

    return {"dispatched": dispatched}


def _dispatch_nudged_processes(repo: Any, runtime: Any, cogent_name: str) -> int:
    """Drain the local ingress queue and dispatch any nudged processes.

    This mirrors the production ingress Lambda: explicitly nudged process IDs
    are dispatched immediately (bypassing weighted random selection), then a
    small batch of other runnable processes is selected.
    """
    ingress_queue = getattr(runtime, "ingress_queue", None)
    if ingress_queue is None:
        return 0

    messages = ingress_queue.drain()
    if not messages:
        return 0

    from cogos.capabilities.scheduler import SchedulerCapability, SchedulerError
    from cogos.db.models import ProcessStatus

    if hasattr(repo, "_load"):
        repo._load()

    scheduler = SchedulerCapability(repo, _NULL_UUID)
    dispatched = 0

    # First pass: dispatch explicitly nudged process IDs
    seen: set[str] = set()
    for msg in messages:
        pid_str = msg.get("process_id")
        if not pid_str or pid_str in seen:
            continue
        seen.add(pid_str)
        try:
            proc = repo.get_process(UUID(pid_str))
            if proc is None or proc.status != ProcessStatus.RUNNABLE:
                continue
            dispatch_result = scheduler.dispatch_process(process_id=pid_str)
            if isinstance(dispatch_result, SchedulerError):
                logger.warning("Nudge dispatch failed for %s: %s", pid_str, dispatch_result.error)
                continue
            runtime.spawn_executor(cogent_name, pid_str)
            dispatched += 1
        except Exception:
            logger.exception("Failed to dispatch nudged process %s", pid_str)

    # Second pass: pick up to 5 additional runnable processes (like prod ingress)
    try:
        select_result = scheduler.select_processes(slots=5)
        for proc_info in select_result.selected:
            try:
                dispatch_result = scheduler.dispatch_process(process_id=proc_info.id)
                if hasattr(dispatch_result, "error"):
                    continue
                runtime.spawn_executor(cogent_name, proc_info.id)
                dispatched += 1
            except Exception:
                logger.exception("Failed to dispatch process %s", proc_info.name)
    except Exception:
        logger.debug("select_processes after nudge failed", exc_info=True)

    if dispatched:
        logger.info("Ingress nudge dispatched %d process(es)", dispatched)

    return dispatched


def run_loop(repo: Any, runtime: Any, cogent_name: str, *, tick_interval: int = _DEFAULT_TICK_INTERVAL) -> None:
    """Tick every *tick_interval* seconds until SIGINT/SIGTERM.

    Between full ticks the loop drains the local ingress queue (SQS mock)
    every second so that channel-message nudges trigger near-instant dispatch.
    """
    # Seed a local daemon executor so processes with no tags (or "python" tag) get dispatched
    from cogos.db.models.executor import Executor
    local_executor = Executor(
        executor_id="local-daemon",
        channel_type="local",
        executor_tags=["python"],
        dispatch_type="channel",
        metadata={"local": True},
    )
    repo.register_executor(local_executor)
    logger.info("Registered local-daemon executor")

    shutdown = False

    def _handle_signal(signum: int, frame: Any) -> None:
        nonlocal shutdown
        logger.info("Received signal %s, shutting down", signum)
        shutdown = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    ingress_queue = getattr(runtime, "ingress_queue", None)
    if ingress_queue is not None:
        logger.info(
            "Local dispatcher started for cogent %s (tick every %ds, ingress queue enabled)",
            cogent_name, tick_interval,
        )
    else:
        logger.info("Local dispatcher started for cogent %s (tick every %ds)", cogent_name, tick_interval)

    while not shutdown:
        try:
            result = run_tick(repo, runtime, cogent_name)
            logger.debug("Tick result: %s", result)
        except Exception:
            logger.exception("Tick failed")

        # Between ticks, sleep in 1-second increments but check the ingress
        # queue each iteration for near-instant event-driven dispatch.
        for _ in range(tick_interval):
            if shutdown:
                break
            if ingress_queue is not None:
                try:
                    _dispatch_nudged_processes(repo, runtime, cogent_name)
                except Exception:
                    logger.debug("Ingress drain failed", exc_info=True)
            time.sleep(1)

    logger.info("Local dispatcher stopped")

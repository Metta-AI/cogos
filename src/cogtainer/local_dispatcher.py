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

from cogos.capabilities.scheduler import SchedulerCapability
from cogos.db.protocol import CogosRepositoryInterface
from cogtainer.runtime.base import CogtainerRuntime

logger = logging.getLogger(__name__)

_THROTTLE_COOLDOWN_MS = 300_000  # 5 minutes
_DEFAULT_TICK_INTERVAL = 60  # seconds
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _dispatch_to_matched_executor(
    repo: CogosRepositoryInterface, scheduler: SchedulerCapability, runtime: CogtainerRuntime, cogent_name: str,
    process_id: str, process_name: str,
) -> bool:
    """Dispatch a process to a tag-matched executor.

    Uses dispatch_to_executor for tag matching. Local executors get
    spawn_executor; channel executors get a channel message. Returns
    True if dispatched successfully.
    """
    from cogos.capabilities.scheduler import SchedulerError
    from cogos.db.models import ChannelMessage
    from cogos.runtime.dispatch import build_dispatch_event

    result = scheduler.dispatch_to_executor(process_id=process_id)
    if isinstance(result, SchedulerError):
        # Emit alert so missing-tag issues are visible
        _emit_missing_tags_alert(repo, process_id, process_name, result.error)
        logger.warning("Dispatch failed for %s: %s", process_name, result.error)
        return False

    if result.dispatch_type == "local" or result.executor_id == "local-daemon":
        runtime.spawn_executor(cogent_name, process_id)
    else:
        # Channel dispatch: send work to executor's channel
        exec_ch = repo.get_channel_by_name(f"system:executor:{result.executor_id}")
        if exec_ch:
            payload = build_dispatch_event(repo, result)
            repo.append_channel_message(ChannelMessage(
                channel=exec_ch.id,
                payload=payload,
            ))
            logger.info(
                "Dispatched %s to channel executor %s (run %s)",
                process_name, result.executor_id, result.run_id,
            )
        else:
            logger.error("Executor channel not found for %s", result.executor_id)
            repo.rollback_dispatch(
                UUID(process_id), UUID(result.run_id), None,
                error="executor channel not found",
            )
            return False

    return True


def _emit_missing_tags_alert(repo: CogosRepositoryInterface, process_id: str, process_name: str, error: str) -> None:
    """Emit an alert when no executor matches required tags."""
    from cogos.db.models import Channel, ChannelMessage, ChannelType

    ch_name = "system:executor:error:missing-tags"
    ch = repo.get_channel_by_name(ch_name)
    if not ch:
        ch = Channel(name=ch_name, channel_type=ChannelType.NAMED)
        repo.upsert_channel(ch)
    repo.append_channel_message(ChannelMessage(
        channel=ch.id,
        payload={
            "process_id": process_id,
            "process_name": process_name,
            "error": error,
        },
    ))


def _is_throttle_cooldown_active(repo: CogosRepositoryInterface) -> bool:
    """Check if any recent run was throttled, indicating we should back off."""
    from cogos.db.models import RunStatus

    recent = repo.list_recent_failed_runs(max_age_ms=_THROTTLE_COOLDOWN_MS)
    return any(r.status == RunStatus.THROTTLED for r in recent)


def run_tick(repo: CogosRepositoryInterface, runtime: CogtainerRuntime, cogent_name: str) -> dict:
    """Single scheduler tick. Returns {"dispatched": int}."""
    from cogos.capabilities.scheduler import SchedulerCapability
    from cogos.runtime.schedule import apply_scheduled_messages

    repo.reload()

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

    # 2. Unblock processes that were blocked due to executor unavailability
    try:
        scheduler.unblock_processes()
    except Exception:
        logger.warning("Unblock processes failed", exc_info=True)

    # 2a. Reap dead executor subprocesses
    try:
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

    # 7. Dispatch via executor tag matching
    if select_result.selected:
        for proc in select_result.selected:
            try:
                result = _dispatch_to_matched_executor(repo, scheduler, runtime, cogent_name, proc.id, proc.name)
                if result:
                    dispatched += 1
            except Exception:
                logger.exception("Failed to dispatch process %s", proc.name)

    if dispatched:
        logger.info("Tick dispatched %s processes", dispatched)

    return {"dispatched": dispatched}


def _dispatch_nudged_processes(repo: CogosRepositoryInterface, runtime: CogtainerRuntime, cogent_name: str) -> int:
    """Drain the local ingress queue and dispatch any nudged processes.

    This mirrors the production ingress Lambda: explicitly nudged process IDs
    are dispatched immediately (bypassing weighted random selection), then a
    small batch of other runnable processes is selected.
    """
    ingress_queue = runtime.ingress_queue
    if ingress_queue is None:
        return 0

    messages = ingress_queue.drain()
    if not messages:
        return 0

    from cogos.capabilities.scheduler import SchedulerCapability
    from cogos.db.models import ProcessStatus

    repo.reload()

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
            if _dispatch_to_matched_executor(repo, scheduler, runtime, cogent_name, pid_str, proc.name):
                dispatched += 1
        except Exception:
            logger.exception("Failed to dispatch nudged process %s", pid_str)

    # Second pass: pick up to 5 additional runnable processes (like prod ingress)
    try:
        select_result = scheduler.select_processes(slots=5)
        for proc_info in select_result.selected:
            try:
                if _dispatch_to_matched_executor(repo, scheduler, runtime, cogent_name, proc_info.id, proc_info.name):
                    dispatched += 1
            except Exception:
                logger.exception("Failed to dispatch process %s", proc_info.name)
    except Exception:
        logger.debug("select_processes after nudge failed", exc_info=True)

    if dispatched:
        logger.info("Ingress nudge dispatched %d process(es)", dispatched)

    return dispatched


def _try_dispatch_blocked(
    repo: CogosRepositoryInterface, runtime: CogtainerRuntime, cogent_name: str,
) -> int:
    """Unblock processes and try to dispatch them. Runs between ticks."""
    from cogos.capabilities.scheduler import SchedulerCapability
    from cogos.db.models import ExecutorStatus

    repo.reload()

    runtime.reap_dead_executors(repo)
    repo.heartbeat_executor("local-daemon", status=ExecutorStatus.IDLE)

    scheduler = SchedulerCapability(repo, _NULL_UUID)
    result = scheduler.unblock_processes()
    if not result.unblocked:
        return 0

    dispatched = 0
    select_result = scheduler.select_processes(slots=5)
    for proc_info in select_result.selected:
        try:
            if _dispatch_to_matched_executor(repo, scheduler, runtime, cogent_name, proc_info.id, proc_info.name):
                dispatched += 1
        except Exception:
            logger.debug("Dispatch failed for unblocked %s", proc_info.name, exc_info=True)
    if dispatched:
        logger.info("Unblocked and dispatched %d process(es)", dispatched)
    return dispatched


def run_loop(
    repo: CogosRepositoryInterface, runtime: CogtainerRuntime, cogent_name: str,
    *, tick_interval: int = _DEFAULT_TICK_INTERVAL,
) -> None:
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

    ingress_queue = runtime.ingress_queue
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
        # Also periodically unblock processes and attempt dispatch.
        for i in range(tick_interval):
            if shutdown:
                break
            if ingress_queue is not None:
                try:
                    _dispatch_nudged_processes(repo, runtime, cogent_name)
                except Exception:
                    logger.debug("Ingress drain failed", exc_info=True)
            if i % 5 == 4:
                try:
                    _try_dispatch_blocked(repo, runtime, cogent_name)
                except Exception:
                    logger.debug("Blocked dispatch failed", exc_info=True)
            time.sleep(1)

    logger.info("Local dispatcher stopped")

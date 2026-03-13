"""Dispatcher Lambda: runs one CogOS scheduler tick per invocation.

EventBridge fires this every 60s. Each invocation:
1. Generates virtual system:tick:minute (and system:tick:hour on the hour)
2. Matches channel messages to handlers
3. Selects runnable processes and dispatches executors

Virtual tick events are emitted as channel messages and wake handlers via deliveries.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID

import boto3

from cogtainer.lambdas.shared.config import get_config
from cogtainer.lambdas.shared.logging import setup_logging
from cogos.runtime.ingress import dispatch_ready_processes
from cogos.runtime.schedule import apply_scheduled_messages

logger = setup_logging()


def handler(event: dict, context) -> dict:
    """Lambda entry point: single-shot scheduler tick."""
    from cogos.capabilities.scheduler import SchedulerCapability

    config = get_config()

    try:
        from cogos.db.repository import Repository
        repo = Repository.create()
    except Exception:
        logger.debug("CogOS repository not available, skipping scheduler tick")
        return {"statusCode": 200, "dispatched": 0}

    scheduler = SchedulerCapability(repo, UUID("00000000-0000-0000-0000-000000000000"))
    lambda_client = boto3.client("lambda", region_name=config.region)
    executor_fn = os.environ.get("EXECUTOR_FUNCTION_NAME")
    if not executor_fn:
        safe_name = os.environ.get("COGENT_NAME", "").replace(".", "-")
        executor_fn = f"cogent-{safe_name}-executor"

    # Heartbeat — lets the dashboard show time-since-last-tick
    try:
        repo.set_meta("scheduler:last_tick")
        repo.set_meta("state:modified_at")
    except Exception:
        pass

    # 0. Recover stuck daemons — if RUNNING but no active run, reset to WAITING
    _recover_stuck_daemons(repo)

    # 1. Generate virtual system tick events (not written to event log)
    _apply_system_ticks(repo)

    # 1.5. Auto-create per-user DM handler processes for new authors
    _ensure_dm_handlers(repo)

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

    # 4. Select any remaining runnable processes
    select_result = scheduler.select_processes(slots=5)
    if not select_result.selected:
        return {"statusCode": 200, "dispatched": dispatched}

    # 5. Dispatch each selected process
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


def _recover_stuck_daemons(repo) -> None:
    """Reset daemon processes stuck in RUNNING with no active run."""
    from cogos.db.models import ProcessMode, ProcessStatus, RunStatus

    running = repo.list_processes(status=ProcessStatus.RUNNING)
    for proc in running:
        if proc.mode != ProcessMode.DAEMON:
            continue
        runs = repo.list_runs(process_id=proc.id, limit=1)
        if not runs or runs[0].status != RunStatus.RUNNING:
            repo.update_process_status(proc.id, ProcessStatus.WAITING)
            logger.info("Recovered stuck daemon %s: running -> waiting", proc.name)
            try:
                repo.create_alert(
                    severity="warning",
                    alert_type="scheduler:stuck_daemon",
                    source="dispatcher",
                    message=f"Recovered stuck daemon '{proc.name}': was running with no active run, reset to waiting",
                    metadata={"process_id": str(proc.id), "process_name": proc.name},
                )
            except Exception:
                logger.debug("Could not create alert for stuck daemon %s", proc.name)


def _ensure_dm_handlers(repo) -> None:
    """Auto-create per-user DM handler processes for new Discord DM authors.

    Scans recent messages on io:discord:dm and creates a dedicated
    discord-dm:{author_id} process for each new author, bound to a
    fine-grained io:discord:dm:{author_id} channel.
    """
    from cogos.db.models import (
        Channel, ChannelType, Handler, Process, ProcessCapability,
        ProcessMode, ProcessStatus,
    )
    from cogos.db.models.channel_message import ChannelMessage

    dm_channel = repo.get_channel_by_name("io:discord:dm")
    if dm_channel is None:
        return

    # Get the discord-handle-message process as the "parent" template
    parent = repo.get_process_by_name("discord-handle-message")
    if parent is None:
        return

    # Scan recent DMs (last 50 — enough to catch new authors)
    recent = repo.list_channel_messages(dm_channel.id, limit=50)
    seen_authors: set[str] = set()

    for msg in recent:
        payload = msg.payload or {}
        author_id = payload.get("author_id")
        author_name = payload.get("author", "unknown")
        if not author_id or author_id in seen_authors:
            continue
        seen_authors.add(author_id)

        proc_name = f"discord-dm:{author_id}"
        existing = repo.get_process_by_name(proc_name)
        if existing and existing.status not in (ProcessStatus.COMPLETED, ProcessStatus.DISABLED):
            # Already exists and active — ensure it has a handler
            fine_ch_name = f"io:discord:dm:{author_id}"
            fine_ch = repo.get_channel_by_name(fine_ch_name)
            if fine_ch:
                handlers = repo.list_handlers(process_id=existing.id)
                has_fine = any(h.channel == fine_ch.id for h in handlers)
                if not has_fine:
                    repo.create_handler(Handler(process=existing.id, channel=fine_ch.id))
                    logger.info("Bound existing %s to channel %s", proc_name, fine_ch_name)
            continue

        # Create the per-user DM process
        content = (
            "@{cogos/io/discord/handler.md}\n\n"
            f"You are handling DMs with Discord user {author_id} ({author_name}).\n\n"
            "## Responding\n\n"
            f"Use discord.dm(user_id='{author_id}', content=your_reply) to respond.\n\n"
            "## Context\n\n"
            "On your first activation:\n"
            "1. Use search() to discover all your capabilities\n"
            "2. Use discord.receive(message_type=\"discord:dm\") to read recent DM history for context\n"
        )

        child = Process(
            name=proc_name,
            mode=ProcessMode.DAEMON,
            content=content,
            priority=5.0,
            runner="lambda",
            status=ProcessStatus.WAITING,
            parent_process=parent.id,
        )
        child_id = repo.upsert_process(child)

        # Bind capabilities — same as parent discord-handle-message
        parent_caps = repo.list_process_capabilities(parent.id)
        for pc in parent_caps:
            try:
                repo.create_process_capability(ProcessCapability(
                    process=child_id,
                    capability=pc.capability,
                    name=pc.name,
                    config=pc.config,
                ))
            except Exception:
                pass  # already bound

        # Create fine-grained channel
        fine_ch_name = f"io:discord:dm:{author_id}"
        fine_ch = repo.get_channel_by_name(fine_ch_name)
        if fine_ch is None:
            fine_ch = Channel(name=fine_ch_name, channel_type=ChannelType.NAMED)
            repo.upsert_channel(fine_ch)
            fine_ch = repo.get_channel_by_name(fine_ch_name)

        # Bind handler to fine-grained channel
        repo.create_handler(Handler(process=child_id, channel=fine_ch.id))

        # Copy the message to the fine-grained channel so it's picked up
        repo.append_channel_message(ChannelMessage(
            channel=fine_ch.id,
            sender_process=None,
            payload=msg.payload,
        ))

        logger.info("Created DM handler %s for author %s (%s)", proc_name, author_id, author_name)


def _apply_system_ticks(repo, *, now: datetime | None = None) -> None:
    """Generate virtual system:tick:minute (and :hour) events.

    These now flow through the shared channel scheduler path so both
    local and prod dispatch wake handlers the same way.
    """
    apply_scheduled_messages(repo, now=now or datetime.now(timezone.utc))

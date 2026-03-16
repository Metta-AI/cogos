"""Reboot: kill all processes, clear process table, re-create init."""

from __future__ import annotations

import logging

from cogos.db.models import Process, ProcessMode, ProcessStatus

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{cogos/init.py}"


def reboot(repo) -> dict:
    """Kill all processes, clear process state, create fresh init process.

    Preserves: files, coglets, channels, schemas, resources, cron.
    Clears: processes, runs, deliveries, handlers, process_capabilities, traces (SQL only).
    """
    # 1. Find and kill init (cascade kills everything)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 2. Count what we're clearing
    all_procs = repo.list_processes(limit=10000)
    cleared = len(all_procs)

    # 3. Clear process-related tables
    repo.clear_process_tables()

    # 4. Create fresh init process
    init_proc = Process(
        name="init",
        mode=ProcessMode.ONE_SHOT,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,
        runner="lambda",
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(init_proc)

    logger.info("Reboot complete: cleared %d processes, init queued", cleared)
    return {"cleared_processes": cleared}

"""Reboot: kill all processes, clear process table, re-create init."""

from __future__ import annotations

import logging

from cogos.db.models import Process, ProcessMode, ProcessStatus

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{cogos/init.py}"


def reboot(repo) -> dict:
    """Kill all processes, clear process state, create fresh init process.

    Preserves: files, coglets, channels, schemas, resources, cron.
    Clears: processes, runs, deliveries, handlers, process_capabilities.
    """
    # 1. Find and kill init (cascade kills everything)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 2. Count what we're clearing
    all_procs = repo.list_processes(limit=10000)
    cleared = len(all_procs)

    # 3. Clear process-related tables
    _clear_process_tables(repo)

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


def _clear_process_tables(repo) -> None:
    """Clear all process-related data."""
    if hasattr(repo, "_runs"):
        # LocalRepository -- direct dict access
        repo._runs.clear()
        repo._deliveries.clear()
        repo._handlers.clear()
        repo._process_capabilities.clear()
        repo._processes.clear()
        repo._force_save()
    else:
        # SQL repository
        for table in [
            "cogos_trace", "cogos_delivery", "cogos_run",
            "cogos_handler", "cogos_process_capability", "cogos_process",
        ]:
            try:
                repo.execute(f"DELETE FROM {table}")
            except Exception:
                pass

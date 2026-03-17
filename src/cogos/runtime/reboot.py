"""Reboot: increment epoch, log operation, re-create init."""

from __future__ import annotations

import logging

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.db.models.operation import CogosOperation

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{cogos/init.py}"


def reboot(repo) -> dict:
    """Increment epoch, log operation, create fresh init process.

    Preserves: files, coglets, channels, schemas, resources, cron.
    Old processes/runs/handlers stay in previous epochs, invisible by default.
    """
    from cogos.db.local_repository import ALL_EPOCHS

    # 1. Find and disable init (cascade disables children)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 2. Count current-epoch processes for reporting
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    prev_count = len(all_procs)

    # 3. Increment epoch
    new_epoch = repo.increment_epoch()

    # 4. Log operation
    repo.add_operation(CogosOperation(
        epoch=new_epoch,
        type="reboot",
        metadata={"prev_process_count": prev_count},
    ))

    # 5. Create fresh init process in the new epoch
    init_proc = Process(
        name="init",
        mode=ProcessMode.ONE_SHOT,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,
        runner="lambda",
        status=ProcessStatus.RUNNABLE,
        epoch=new_epoch,
    )
    repo.upsert_process(init_proc)

    logger.info("Reboot complete: epoch=%d, prev_processes=%d", new_epoch, prev_count)
    return {"cleared_processes": prev_count, "epoch": new_epoch}

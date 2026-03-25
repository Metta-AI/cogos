"""Reboot: re-apply image, increment epoch, log operation, re-create init."""

from __future__ import annotations

import logging
from pathlib import Path

from cogos.db.models import ALL_EPOCHS, Process, ProcessCapability, ProcessMode, ProcessStatus
from cogos.db.models.operation import CogosOperation

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{mnt/boot/cogos/init.py}"
INIT_CAPABILITIES = [
    "me", "procs", "fs_dir", "file", "discord", "channels",
    "secrets", "alerts", "cogent", "history",
    "blob", "image",
    "asana", "email", "github", "web_search", "web_fetch", "web",
    "cog_registry", "coglet_runtime",
    "monitor",
]

# Standard image locations (cogtainer: /app/images/cogos, local dev: ./images/cogos)
_IMAGE_SEARCH_PATHS = [
    Path("/app/images/cogos"),
    Path("images/cogos"),
]


def _find_image_dir() -> Path | None:
    for p in _IMAGE_SEARCH_PATHS:
        if p.is_dir():
            return p
    return None


def reboot(repo) -> dict:
    """Re-apply image, increment epoch, create fresh init process.

    Re-applies the image from the bundled images/ directory so FileStore
    picks up the latest code. Old processes stay in previous epochs.
    """

    # 0. Ensure DB schema is up to date before touching anything
    try:
        from cogos.db.migrations import apply_cogos_sql_migrations
        apply_cogos_sql_migrations(repo, on_error=lambda f, e: logger.debug("migration %s: %s", f, e))
    except Exception:
        logger.debug("CogOS SQL migrations failed", exc_info=True)

    # 1. Re-apply image to update FileStore with current code
    image_counts = {}
    image_dir = _find_image_dir()
    if image_dir:
        from cogos.image.apply import apply_image
        from cogos.image.spec import load_image

        spec = load_image(image_dir)
        image_counts = apply_image(spec, repo)
        logger.info("Image re-applied: %s", image_counts)

    # 2. Find and disable init (cascade disables children)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 3. Count current-epoch processes for reporting
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    prev_count = len(all_procs)

    # 4. Increment epoch
    new_epoch = repo.increment_epoch()

    # 5. Log operation
    repo.add_operation(CogosOperation(
        epoch=new_epoch,
        type="reboot",
        metadata={"prev_process_count": prev_count, "image": image_counts},
    ))

    # 6. Create fresh init process in the new epoch
    init_proc = Process(
        name="init",
        mode=ProcessMode.DAEMON,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,
        status=ProcessStatus.RUNNABLE,
        epoch=new_epoch,
    )
    pid = repo.upsert_process(init_proc)

    # 7. Bind capabilities — same set declared in init/processes.py
    bound = 0
    for cap_name in INIT_CAPABILITIES:
        cap = repo.get_capability_by_name(cap_name)
        if cap:
            try:
                repo.create_process_capability(
                    ProcessCapability(process=pid, capability=cap.id, name=cap_name, epoch=new_epoch)
                )
                bound += 1
            except Exception:
                logger.warning("Failed to bind capability %s to init", cap_name, exc_info=True)
    if bound == 0:
        logger.error("No capabilities bound to init — sandbox will crash")

    logger.info("Reboot complete: epoch=%d, prev_processes=%d", new_epoch, prev_count)
    return {"cleared_processes": prev_count, "epoch": new_epoch}

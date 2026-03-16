"""Load Process definitions from Python files and sync to the datastore.

Legacy note: this module predates the channel-based handler model and still
documents the older event-pattern flow used by the `src/cogents/` loader
stack. Current CogOS images and CLIs model handlers as process-to-channel
subscriptions instead.

Each file must define one or more top-level variables whose values are
``Process`` instances, optionally accompanied by ``Handler`` and
``ProcessCapability`` instances that bind event patterns and capabilities
to the process.

Legacy example file::

    from cogos.db.models.process import Process, ProcessMode
    from cogos.db.models.handler import Handler
    from cogos.db.models.process_capability import ProcessCapability

    triage = Process(
        name="triage-issue",
        mode=ProcessMode.ONE_SHOT,
        content="Triage incoming GitHub issues.",
        runner="lambda",
    )

    triage_handler = Handler(
        process=triage.id,
        event_pattern="github.issue.opened",
    )

    triage_caps = ProcessCapability(
        process=triage.id,
        capability=...,  # resolved at sync time by name
    )

For convenience, processes can also declare handlers and capabilities inline
via metadata keys in this legacy loader:

    triage = Process(
        name="triage-issue",
        metadata={
            "handlers": ["github.issue.opened"],
            "capabilities": ["files/read", "files/write", "events/emit"],
        },
    )
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from cogos.db.models.handler import Handler
from cogos.db.models.process import Process
from cogos.db.models.process_capability import ProcessCapability
from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


def _load_module(path: Path, module_name: str):
    """Import a .py file as a module."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_processes_from_file(path: Path) -> list[Process]:
    """Import a .py file and return all top-level Process instances."""
    module_name = f"_cogents_loader_.{path.stem}"
    module = _load_module(path, module_name)
    return [
        v for v in vars(module).values()
        if isinstance(v, Process)
    ]


def load_processes_from_dir(root: Path) -> list[Process]:
    """Recursively load Process instances from all .py files under *root*."""
    processes: list[Process] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            processes.extend(load_processes_from_file(path))
        except Exception:
            logger.exception("Failed to load processes from %s", path)
    return processes


def _sync_inline_handlers(proc: Process, repo: Repository) -> int:
    """Legacy event-pattern sync path for older ``src/cogents/`` loaders.

    Current CogOS handlers subscribe processes to channels. New code should use
    the image/apply flow or the channel-based CLI in ``src/cogos/cli/__main__.py``.

    Returns the number of newly created handlers.
    """
    patterns = proc.metadata.get("handlers", [])
    if not patterns:
        return 0
    existing = repo.list_handlers(process_id=proc.id)
    # Legacy-only path: older Handler objects exposed ``event_pattern``.
    existing_patterns = {h.event_pattern for h in existing}
    count = 0
    for pattern in patterns:
        if pattern in existing_patterns:
            continue
        repo.create_handler(Handler(process=proc.id, event_pattern=pattern))
        count += 1
    return count


def _sync_inline_capabilities(proc: Process, repo: Repository) -> int:
    """Bind capabilities from ``metadata["capabilities"]`` names."""
    cap_names = proc.metadata.get("capabilities", [])
    if not cap_names:
        return 0
    existing = repo.list_process_capabilities(proc.id)
    existing_cap_ids = {pc.capability for pc in existing}
    count = 0
    for cap_name in cap_names:
        cap = repo.get_capability_by_name(cap_name)
        if cap is None:
            logger.warning(
                "Capability %r not found for process %s — skipping",
                cap_name, proc.name,
            )
            continue
        if cap.id in existing_cap_ids:
            continue
        repo.create_process_capability(
            ProcessCapability(process=proc.id, capability=cap.id)
        )
        count += 1
    return count


def sync_processes(root: Path, repo: Repository) -> tuple[int, int]:
    """Load all processes from *root* and upsert into the datastore.

    Also syncs inline handlers and capability bindings declared in
    ``metadata["handlers"]`` and ``metadata["capabilities"]``.

    The inline handler support here is legacy and assumes event-pattern
    handlers, not the current channel-subscription model.

    Returns ``(synced, errors)``.
    """
    processes = load_processes_from_dir(root)
    synced = 0
    errors = 0
    for proc in processes:
        try:
            repo.upsert_process(proc)
            _sync_inline_handlers(proc, repo)
            _sync_inline_capabilities(proc, repo)
            synced += 1
            logger.info("Synced process %s", proc.name)
        except Exception:
            logger.exception("Failed to sync process %s", proc.name)
            errors += 1
    return synced, errors

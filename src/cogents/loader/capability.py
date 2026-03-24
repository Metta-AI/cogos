"""Load Capability definitions from Python files and sync to the datastore.

Each file must define one or more top-level variables whose values are
``Capability`` instances.  The loader imports every ``.py`` file under a
directory, extracts the Capability objects, and upserts them.

Example file (``init/capabilities/run_code.py``)::

    from cogos.db.models.capability import Capability

    run_code = Capability(
        name="sandbox/run_code",
        description="Execute Python in a sandbox.",
        handler="cogos.sandbox.executor.execute",
        ...
    )
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from cogos.db.models.capability import Capability
from cogos.db.protocol import CogosRepositoryInterface

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


def load_capabilities_from_file(path: Path) -> list[Capability]:
    """Import a .py file and return all top-level Capability instances."""
    module_name = f"_cogents_loader_.{path.stem}"
    module = _load_module(path, module_name)
    return [
        v for v in vars(module).values()
        if isinstance(v, Capability)
    ]


def load_capabilities_from_dir(root: Path) -> list[Capability]:
    """Recursively load Capability instances from all .py files under *root*."""
    capabilities: list[Capability] = []
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            capabilities.extend(load_capabilities_from_file(path))
        except Exception:
            logger.exception("Failed to load capabilities from %s", path)
    return capabilities


def sync_capabilities(root: Path, repo: CogosRepositoryInterface) -> tuple[int, int]:
    """Load all capabilities from *root* and upsert into the datastore.

    Returns ``(synced, errors)``.
    """
    capabilities = load_capabilities_from_dir(root)
    synced = 0
    errors = 0
    for cap in capabilities:
        try:
            repo.upsert_capability(cap)
            synced += 1
            logger.info("Synced capability %s", cap.name)
        except Exception:
            logger.exception("Failed to sync capability %s", cap.name)
            errors += 1
    return synced, errors

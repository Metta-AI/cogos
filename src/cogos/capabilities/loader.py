"""Shared capability loader — builds capability proxy instances for a process.

Used by both the sandbox MCP server and the CogOS API service.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any
from uuid import UUID

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


def build_capability_proxies(
    repo: Repository,
    process_id: UUID,
    *,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
    secrets_provider: Any = None,
    runtime: Any = None,
) -> dict[str, object]:
    """Load capabilities bound to a process and build proxy objects.

    Each capability class is instantiated with (repo, process_id) and
    injected under its grant name (e.g. ``email_me``).
    If scope config exists on the grant, the instance is scoped accordingly.
    """
    from cogos.capabilities.me import MeCapability

    pcs = repo.list_process_capabilities(process_id)
    proxies: dict[str, object] = {}
    for pc in pcs:
        cap = repo.get_capability(pc.capability)
        if cap is None or not cap.enabled:
            continue

        handler = _resolve_handler(cap.handler)
        if handler is None:
            continue

        # Use the grant name as the namespace key; fall back to capability name
        ns = pc.name or cap.name.split("/")[0]

        # Class capabilities get instantiated with repo and process_id
        if inspect.isclass(handler):
            kwargs: dict[str, Any] = {"run_id": run_id}
            if trace_id is not None:
                kwargs["trace_id"] = trace_id
            if secrets_provider is not None:
                kwargs["secrets_provider"] = secrets_provider
            if runtime is not None:
                kwargs["runtime"] = runtime

            if issubclass(handler, MeCapability):
                instance = handler(repo, process_id, **kwargs)
            else:
                instance = handler(repo, process_id, **kwargs)

            # Apply scope config if present
            if pc.config and hasattr(instance, "scope"):
                instance = instance.scope(**pc.config)
            proxies[ns] = instance
        else:
            proxies[ns] = handler
    return proxies


def _resolve_handler(handler_path: str) -> Any | None:
    """Resolve a dotted handler path to a class or callable."""
    if ":" in handler_path:
        mod_path, attr_name = handler_path.rsplit(":", 1)
    elif "." in handler_path:
        mod_path, attr_name = handler_path.rsplit(".", 1)
    else:
        return None

    try:
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Could not load handler %s: %s", handler_path, exc)
        return None

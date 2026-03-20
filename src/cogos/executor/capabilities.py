"""Capability loading for executor — builds scoped capability instances from DB bindings."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any
from uuid import UUID

from cogos.db.repository import Repository

logger = logging.getLogger(__name__)


def build_process_capabilities(
    process_id: UUID,
    repo: Repository,
    *,
    run_id: UUID | None = None,
    trace_id: UUID | None = None,
    runtime: Any | None = None,
) -> dict[str, Any]:
    """Load capability instances bound to a process, with scope applied.

    Returns dict mapping namespace name to scoped Capability instance.
    Only capabilities explicitly bound via ProcessCapability are included.
    """
    result: dict[str, Any] = {}
    pcs = repo.list_process_capabilities(process_id)

    for pc in pcs:
        cap_model = repo.get_capability(pc.capability)
        if cap_model is None or not cap_model.enabled:
            continue

        ns = pc.name or (cap_model.name.split("/")[0] if "/" in cap_model.name else cap_model.name)
        handler_path = cap_model.handler
        if not handler_path:
            continue

        if ":" in handler_path:
            mod_path, attr_name = handler_path.rsplit(":", 1)
        elif "." in handler_path:
            mod_path, attr_name = handler_path.rsplit(".", 1)
        else:
            continue

        try:
            mod = importlib.import_module(mod_path)
            handler_cls = getattr(mod, attr_name)
            if not callable(handler_cls):
                result[ns] = handler_cls
                continue

            try:
                init_sig = inspect.signature(handler_cls.__init__)
                init_params = init_sig.parameters
            except (ValueError, TypeError):
                init_params = {}

            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in init_params.values())
            kwargs: dict[str, Any] = {}
            if "run_id" in init_params or has_var_keyword:
                kwargs["run_id"] = run_id
            if "trace_id" in init_params or has_var_keyword:
                kwargs["trace_id"] = trace_id
            if runtime and ("runtime" in init_params or has_var_keyword):
                kwargs["runtime"] = runtime
            if runtime and ("secrets_provider" in init_params or has_var_keyword):
                kwargs["secrets_provider"] = runtime.get_secrets_provider()

            instance = handler_cls(repo, process_id, **kwargs)
            if pc.config:
                instance = instance.scope(**pc.config)

            result[ns] = instance
        except (ImportError, AttributeError) as exc:
            logger.warning("Could not load capability %s (%s): %s", cap_model.name, handler_path, exc)

    return result

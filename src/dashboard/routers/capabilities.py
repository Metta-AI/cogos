from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cogos.db.models import Capability
from dashboard.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cogos-capabilities"])


# ── Response / request models ──────────────────────────────────────


class CapabilityOut(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    handler: str
    schema: dict
    iam_role_arn: str | None = None
    enabled: bool
    metadata: dict
    created_at: str | None = None
    updated_at: str | None = None


class CapabilityUpdate(BaseModel):
    enabled: bool | None = None
    description: str | None = None
    instructions: str | None = None
    handler: str | None = None
    schema: dict | None = None
    metadata: dict | None = None


class CapabilitiesResponse(BaseModel):
    count: int
    capabilities: list[CapabilityOut]


# ── Helpers ─────────────────────────────────────────────────────────


def _to_out(c: Capability) -> CapabilityOut:
    return CapabilityOut(
        id=str(c.id),
        name=c.name,
        description=c.description,
        instructions=c.instructions,
        handler=c.handler,
        schema=c.schema,
        iam_role_arn=c.iam_role_arn,
        enabled=c.enabled,
        metadata=c.metadata,
        created_at=str(c.created_at) if c.created_at else None,
        updated_at=str(c.updated_at) if c.updated_at else None,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/capabilities", response_model=CapabilitiesResponse)
def list_capabilities(name: str) -> CapabilitiesResponse:
    repo = get_repo()
    items = repo.list_capabilities()
    out = [_to_out(c) for c in items]
    return CapabilitiesResponse(count=len(out), capabilities=out)


@router.get("/capabilities/{cap_name}")
def get_capability(name: str, cap_name: str) -> dict:
    repo = get_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")
    return _to_out(c).model_dump()


@router.put("/capabilities/{cap_name}", response_model=CapabilityOut)
def update_capability(name: str, cap_name: str, body: CapabilityUpdate) -> CapabilityOut:
    repo = get_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")

    if body.enabled is not None:
        c.enabled = body.enabled
    if body.description is not None:
        c.description = body.description
    if body.instructions is not None:
        c.instructions = body.instructions
    if body.handler is not None:
        c.handler = body.handler
    if body.schema is not None:
        c.schema = body.schema
    if body.metadata is not None:
        c.metadata = body.metadata

    repo.upsert_capability(c)
    return _to_out(c)


class CapabilityProcessOut(BaseModel):
    process_id: str
    process_name: str
    process_status: str
    grant_name: str = ""
    config: dict | None = None


@router.get("/capabilities/{cap_name}/process")
def list_capability_processes(name: str, cap_name: str) -> list[dict]:
    repo = get_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")
    return repo.list_processes_for_capability(c.id)


# ── Method introspection ───────────────────────────────────────────


class MethodParam(BaseModel):
    name: str
    type: str
    default: str | None = None


class MethodInfo(BaseModel):
    name: str
    params: list[MethodParam]
    return_type: str


@router.get("/capabilities/{cap_name}/methods", response_model=list[MethodInfo])
def get_capability_methods(name: str, cap_name: str) -> list[MethodInfo]:
    """Introspect the handler class to return its public methods."""
    repo = get_repo()
    c = repo.get_capability_by_name(cap_name)
    if not c:
        raise HTTPException(status_code=404, detail="Capability not found")

    if not c.handler:
        return []

    return _introspect_handler(c.handler)


def _introspect_handler(handler_path: str) -> list[MethodInfo]:
    """Import a handler class and extract public method signatures."""
    import importlib
    import inspect

    try:
        module_path, class_name = handler_path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
    except Exception:
        logger.warning("Could not import handler %s", handler_path)
        return []

    methods: list[MethodInfo] = []
    for method_name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        if method_name.startswith("_"):
            continue

        sig = inspect.signature(method)
        hints = getattr(method, "__annotations__", {})

        params: list[MethodParam] = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            ptype = hints.get(pname, "")
            if hasattr(ptype, "__name__"):
                ptype = ptype.__name__
            elif ptype:
                ptype = str(ptype)
            default = None
            if param.default is not inspect.Parameter.empty:
                default = repr(param.default)
            params.append(MethodParam(name=pname, type=ptype, default=default))

        ret = hints.get("return", "")
        if hasattr(ret, "__name__"):
            ret = ret.__name__
        elif ret:
            ret = str(ret)
        else:
            ret = ""

        methods.append(MethodInfo(name=method_name, params=params, return_type=str(ret)))

    return methods

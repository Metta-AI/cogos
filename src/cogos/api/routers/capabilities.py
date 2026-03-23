"""Capability proxy — discovery and invocation endpoints."""

from __future__ import annotations

import inspect
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.loader import build_capability_proxies
from cogos.api.auth import AuthContext, validate_token
from cogos.api.db import get_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["capabilities"])


# ── Response models ───────────────────────────────────────────


class CapabilityInfo(BaseModel):
    name: str
    class_name: str
    methods: list[str]
    help: str = ""


class CapabilitiesListResponse(BaseModel):
    capabilities: list[CapabilityInfo]


class MethodParam(BaseModel):
    name: str
    type: str
    default: str | None = None
    required: bool = True


class MethodDetail(BaseModel):
    name: str
    params: list[MethodParam]
    return_type: str
    docstring: str = ""


class InvokeRequest(BaseModel):
    args: dict[str, Any] = {}
    scope: dict[str, Any] | None = None


class InvokeResponse(BaseModel):
    result: Any = None
    error: str | None = None


# ── Helpers ───────────────────────────────────────────────────


def _get_proxies(auth: AuthContext) -> dict[str, object]:
    """Build capability proxies for the authenticated process."""
    if not auth.process_id:
        raise HTTPException(status_code=400, detail="X-Process-Id header required")
    repo = get_repo()
    pid = UUID(auth.process_id)
    return build_capability_proxies(repo, pid)


def _get_cap(proxies: dict[str, object], cap_name: str) -> Capability:
    """Look up a capability by name, raising 404 if not found."""
    proxy = proxies.get(cap_name)
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Capability '{cap_name}' not found or not granted")
    if not isinstance(proxy, Capability):
        raise HTTPException(status_code=400, detail=f"'{cap_name}' is not a class-based capability")
    return proxy


def _public_methods(cap: Capability) -> list[str]:
    """Return names of public methods on a capability (excluding base helpers)."""
    return sorted(
        name
        for name, _ in inspect.getmembers(type(cap), predicate=inspect.isfunction)
        if not name.startswith("_") and name not in ("help", "scope")
    )


def _introspect_method(cap: Capability, method_name: str) -> MethodDetail:
    """Return detailed signature info for a capability method."""
    method = getattr(type(cap), method_name, None)
    if method is None:
        raise HTTPException(status_code=404, detail=f"Method '{method_name}' not found")

    import typing

    sig = inspect.signature(method)
    hints = typing.get_type_hints(method)

    params: list[MethodParam] = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ptype = hints.get(pname)
        type_str = getattr(ptype, "__name__", str(ptype)) if ptype else "Any"
        default = None
        required = True
        if param.default is not inspect.Parameter.empty:
            default = repr(param.default)
            required = False
        params.append(MethodParam(name=pname, type=type_str, default=default, required=required))

    ret = hints.get("return")
    ret_str = getattr(ret, "__name__", str(ret)) if ret else ""

    docstring = (method.__doc__ or "").strip().split("\n")[0] if method.__doc__ else ""

    return MethodDetail(name=method_name, params=params, return_type=ret_str, docstring=docstring)


def _serialize_result(value: Any) -> Any:
    """Serialize a capability return value for JSON response."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_result(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    # Fall back to repr for unknown types
    return repr(value)


# ── Routes ────────────────────────────────────────────────────


@router.get("/capabilities", response_model=CapabilitiesListResponse)
def list_capabilities(auth: AuthContext = Depends(validate_token)) -> CapabilitiesListResponse:
    """List capabilities available to the authenticated process."""
    proxies = _get_proxies(auth)
    items = []
    for name, proxy in sorted(proxies.items()):
        if isinstance(proxy, Capability):
            methods = _public_methods(proxy)
            try:
                help_text = proxy.help()
            except Exception:
                help_text = ""
            items.append(CapabilityInfo(
                name=name,
                class_name=type(proxy).__name__,
                methods=methods,
                help=help_text,
            ))
    return CapabilitiesListResponse(capabilities=items)


@router.get("/capabilities/{cap_name}")
def get_capability(cap_name: str, auth: AuthContext = Depends(validate_token)) -> CapabilityInfo:
    """Get details for a specific capability."""
    proxies = _get_proxies(auth)
    cap = _get_cap(proxies, cap_name)
    methods = _public_methods(cap)
    try:
        help_text = cap.help()
    except Exception:
        help_text = ""
    return CapabilityInfo(
        name=cap_name,
        class_name=type(cap).__name__,
        methods=methods,
        help=help_text,
    )


@router.get("/capabilities/{cap_name}/methods")
def list_methods(cap_name: str, auth: AuthContext = Depends(validate_token)) -> list[MethodDetail]:
    """List methods with signatures for a capability."""
    proxies = _get_proxies(auth)
    cap = _get_cap(proxies, cap_name)
    method_names = _public_methods(cap)
    return [_introspect_method(cap, m) for m in method_names]


@router.get("/capabilities/{cap_name}/methods/{method_name}")
def get_method(cap_name: str, method_name: str, auth: AuthContext = Depends(validate_token)) -> MethodDetail:
    """Get detailed signature for a specific method."""
    proxies = _get_proxies(auth)
    cap = _get_cap(proxies, cap_name)
    if method_name.startswith("_") or method_name in ("help", "scope"):
        raise HTTPException(status_code=404, detail=f"Method '{method_name}' not found")
    return _introspect_method(cap, method_name)


@router.post("/capabilities/{cap_name}/{method_name}", response_model=InvokeResponse)
def invoke_method(
    cap_name: str,
    method_name: str,
    body: InvokeRequest,
    auth: AuthContext = Depends(validate_token),
) -> InvokeResponse:
    """Invoke a capability method with the provided arguments.

    The capability is instantiated with the session's process_id and
    scoped according to the process grant + optional request scope.
    """
    proxies = _get_proxies(auth)
    cap = _get_cap(proxies, cap_name)

    # Block private/internal methods
    if method_name.startswith("_") or method_name in ("help", "scope"):
        raise HTTPException(status_code=403, detail=f"Cannot invoke '{method_name}'")

    method = getattr(cap, method_name, None)
    if method is None or not callable(method):
        raise HTTPException(status_code=404, detail=f"Method '{method_name}' not found on '{cap_name}'")

    # Apply additional scope if requested (intersects with existing grant scope)
    target = cap
    if body.scope:
        try:
            target = cap.scope(**body.scope)
        except Exception as exc:
            return InvokeResponse(error=f"Scope error: {exc}")

    method = getattr(target, method_name)

    try:
        result = method(**body.args)
        return InvokeResponse(result=_serialize_result(result))
    except PermissionError as exc:
        return InvokeResponse(error=f"Permission denied: {exc}")
    except TypeError as exc:
        return InvokeResponse(error=f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.exception("Capability invocation failed: %s.%s", cap_name, method_name)
        return InvokeResponse(error=f"{type(exc).__name__}: {exc}")

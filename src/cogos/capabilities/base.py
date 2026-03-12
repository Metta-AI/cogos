"""Base capability class — all capabilities inherit from this."""

from __future__ import annotations

import copy
import inspect
import typing
from uuid import UUID

from pydantic import BaseModel

from cogos.db.repository import Repository


def _describe_type(tp: type | None) -> str:
    """Return a concise human-readable string for a type annotation."""
    if tp is None or tp is inspect.Parameter.empty:
        return "Any"

    origin = typing.get_origin(tp)

    # Union / X | Y  (includes Optional)
    if origin is typing.Union:
        args = typing.get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return f"{_describe_type(non_none[0])} | None"
        return " | ".join(_describe_type(a) for a in args if a is not type(None))

    # list[X], dict[K,V], etc.
    if origin is not None:
        name = getattr(origin, "__name__", str(origin))
        args = typing.get_args(tp)
        if args:
            inner = ", ".join(_describe_type(a) for a in args)
            return f"{name}[{inner}]"
        return name

    # Pydantic model — just use its class name
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return tp.__name__

    return getattr(tp, "__name__", str(tp))


def _describe_pydantic(model_cls: type) -> list[str]:
    """Return field descriptions for a Pydantic model class."""
    if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
        return []
    from pydantic_core import PydanticUndefined

    lines: list[str] = []
    for name, field in model_cls.model_fields.items():
        ftype = _describe_type(field.annotation)
        default = ""
        if field.default is PydanticUndefined:
            default = " (required)"
        elif field.default is not None:
            default = f" = {field.default!r}"
        desc = f"  {name}: {ftype}{default}"
        if field.description:
            desc += f"  -- {field.description}"
        lines.append(desc)
    return lines


def _method_help(method: callable) -> str:
    """Generate help text for a single method, including IO schemas."""
    sig = inspect.signature(method)
    hints = typing.get_type_hints(method)

    # Parameters (skip self)
    params: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        ptype = _describe_type(hints.get(pname))
        if param.default is not inspect.Parameter.empty:
            params.append(f"{pname}: {ptype} = {param.default!r}")
        else:
            params.append(f"{pname}: {ptype}")

    ret_type = hints.get("return")
    ret_str = _describe_type(ret_type)
    header = f"{method.__name__}({', '.join(params)}) -> {ret_str}"

    lines = [header]

    # Docstring (first line only)
    if method.__doc__:
        first_line = method.__doc__.strip().split("\n")[0]
        lines.append(f"  {first_line}")

    # Expand Pydantic return types
    ret_models: list[type] = []
    if typing.get_origin(ret_type) is typing.Union:
        ret_models = [a for a in typing.get_args(ret_type)
                      if isinstance(a, type) and issubclass(a, BaseModel)]
    elif isinstance(ret_type, type) and issubclass(ret_type, BaseModel):
        ret_models = [ret_type]

    # Also check for list[PydanticModel]
    if typing.get_origin(ret_type) is list:
        inner = typing.get_args(ret_type)
        if inner and isinstance(inner[0], type) and issubclass(inner[0], BaseModel):
            ret_models = [inner[0]]

    for model in ret_models:
        lines.append(f"  {model.__name__}:")
        lines.extend(f"  {l}" for l in _describe_pydantic(model))

    return "\n".join(lines)


class Capability:
    """Base class for CogOS capabilities.

    Subclasses define typed methods that processes call in the sandbox.
    Each capability is instantiated once per process session with a
    repository handle and the owning process ID.
    """

    def __init__(self, repo: Repository, process_id: UUID) -> None:
        self.repo = repo
        self.process_id = process_id
        self._scope: dict = {}

    def scope(self, **kwargs: object) -> Capability:
        """Return a clone of this capability with a narrower scope.

        Never modifies the original instance.
        """
        new_scope = self._narrow(self._scope, kwargs)
        clone = copy.copy(self)
        clone._scope = new_scope
        return clone

    def _narrow(self, existing: dict, requested: dict) -> dict:
        """Compute the new scope from existing and requested constraints.

        Default implementation: merge dicts (requested overrides existing).
        Subclasses should override for intersection / validation logic.
        """
        return {**existing, **requested}

    def _check(self, op: str, **context: object) -> None:
        """Verify that *op* is allowed under the current scope.

        Default implementation: no enforcement (everything allowed).
        Subclasses should override to raise ``PermissionError`` when needed.
        """

    def help(self) -> str:
        """Describe this capability: all public methods with signatures and IO schemas."""
        cls = type(self)
        name = cls.__name__
        lines = [name]

        # Class docstring
        if cls.__doc__:
            for line in cls.__doc__.strip().split("\n"):
                lines.append(f"  {line.strip()}")

        lines.append("")

        # Public methods (exclude help itself and dunders)
        methods = inspect.getmembers(cls, predicate=inspect.isfunction)
        for mname, method in sorted(methods):
            if mname.startswith("_") or mname == "help":
                continue
            lines.append(_method_help(method))
            lines.append("")

        return "\n".join(lines)
